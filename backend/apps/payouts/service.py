"""
Payout creation service.

Critical path — every decision here has a correctness reason:

1. LOCKING: We SELECT FOR UPDATE the Merchant row before computing balance.
   This serialises concurrent payout creation for the same merchant.
   Without this lock, two threads can both read balance=100, both see
   it's enough for 60, both create holds — netting -120 against a 100 balance.

2. AGGREGATION: Balance is computed via DB SUM inside the same transaction.
   The lock guarantees no other payout_hold can be inserted between our
   aggregate and our own insert.

3. IDEMPOTENCY: We first check for an existing idempotency key (SELECT FOR UPDATE
   on that row to handle concurrent duplicate requests). Only if absent do we
   proceed to create the payout.

4. ATOMICITY: The entire sequence (read lock → aggregate → insert payout → insert
   ledger hold → mark idempotency complete) runs inside ONE transaction.
   Any failure rolls back everything.
"""

import logging
import uuid
from datetime import timedelta

from django.conf import settings
from django.db import transaction
from django.utils import timezone

from apps.ledger.models import LedgerEntry, LedgerEntryType
from apps.ledger.queries import get_merchant_balance
from apps.merchants.models import BankAccount, Merchant
from apps.payouts.exceptions import (
    IdempotencyConflictError,
    InsufficientFundsError,
)
from apps.payouts.models import IdempotencyKey, Payout, PayoutState

logger = logging.getLogger(__name__)


def create_payout(
    *,
    merchant_id: uuid.UUID,
    bank_account_id: uuid.UUID,
    amount_paise: int,
    idempotency_key_str: str,
) -> tuple[Payout, bool]:
    """
    Create a payout atomically.

    Returns (payout, created) where created=False means an idempotent replay.

    Raises:
        InsufficientFundsError  — balance too low
        IdempotencyConflictError — same key is currently being processed
        BankAccount.DoesNotExist — invalid bank account
        Merchant.DoesNotExist   — unknown merchant
    """
    if amount_paise <= 0:
        raise ValueError(f"amount_paise must be positive, got {amount_paise}")

    with transaction.atomic():
        # ── Step 1: Lock the merchant row ────────────────────────────────────
        # SELECT FOR UPDATE on the merchant row serialises all concurrent payout
        # creations for this merchant. Any other transaction that tries to create
        # a payout for the same merchant will block here until we commit.
        merchant = Merchant.objects.select_for_update().get(pk=merchant_id)

        # ── Step 2: Idempotency check (inside the lock) ───────────────────────
        # We also SELECT FOR UPDATE on the idempotency key so that two concurrent
        # requests with the same key don't both see "no record" and both proceed.
        try:
            idem_key = IdempotencyKey.objects.select_for_update().get(
                merchant=merchant,
                key=idempotency_key_str,
                expires_at__gt=timezone.now(),
            )
            if idem_key.status == IdempotencyKey.Status.IN_PROGRESS:
                # Another request with this key is mid-flight
                raise IdempotencyConflictError(
                    f"Idempotency key '{idempotency_key_str}' is currently being processed. "
                    "Retry after a moment."
                )
            # Key is complete — return the stored payout
            logger.info(
                "Idempotent replay for key=%s merchant=%s", idempotency_key_str, merchant_id
            )
            return idem_key.payout, False

        except IdempotencyKey.DoesNotExist:
            pass

        # ── Step 3: Create idempotency record (in_progress) ──────────────────
        # Do this BEFORE balance check so that a concurrent request with the same
        # key (that arrives while we are processing) hits the IN_PROGRESS guard above.
        idem_key = IdempotencyKey.objects.create(
            merchant=merchant,
            key=idempotency_key_str,
            status=IdempotencyKey.Status.IN_PROGRESS,
            expires_at=timezone.now() + timedelta(hours=settings.PAYOUT_IDEMPOTENCY_TTL_HOURS),
        )

        # ── Step 4: Validate bank account belongs to merchant ─────────────────
        bank_account = BankAccount.objects.get(pk=bank_account_id, merchant=merchant, is_active=True)

        # ── Step 5: Compute available balance via DB aggregate ───────────────
        # This runs AFTER acquiring the merchant lock, so the balance reflects
        # all committed ledger entries and no other concurrent payout can insert
        # a hold until our transaction commits.
        balance = get_merchant_balance(merchant_id)
        available_paise = balance["available_paise"]

        logger.info(
            "Balance check merchant=%s available=%d requested=%d",
            merchant_id,
            available_paise,
            amount_paise,
        )

        if available_paise < amount_paise:
            # Roll back the idempotency record — this request legitimately failed
            # due to business rules, not a system error. We do NOT store it as
            # complete so the merchant can retry after topping up.
            idem_key.delete()
            raise InsufficientFundsError(
                f"Insufficient funds: available {available_paise} paise, "
                f"requested {amount_paise} paise."
            )

        # ── Step 6: Create the payout ─────────────────────────────────────────
        payout = Payout.objects.create(
            merchant=merchant,
            bank_account=bank_account,
            amount_paise=amount_paise,
            state=PayoutState.PENDING,
        )

        # ── Step 7: Create the ledger hold entry ──────────────────────────────
        # amount is negative (funds are reserved / removed from available balance)
        LedgerEntry.objects.create(
            merchant=merchant,
            amount=-amount_paise,
            type=LedgerEntryType.PAYOUT_HOLD,
            reference_id=payout.id,
        )

        # ── Step 8: Mark idempotency key as complete ──────────────────────────
        idem_key.payout = payout
        idem_key.status = IdempotencyKey.Status.COMPLETE
        idem_key.save(update_fields=["payout", "status"])

        logger.info("Payout created id=%s merchant=%s amount=%d", payout.id, merchant_id, amount_paise)
        return payout, True


def settle_payout_success(payout: Payout) -> None:
    """
    Atomically: transition state to completed + release hold + create debit.
    Net ledger effect: release(+X) + debit(-X) = 0 change to available.
    The hold(-X) already removed the funds; debit makes the book permanent.
    """
    with transaction.atomic():
        payout.transition_to(PayoutState.COMPLETED)

        LedgerEntry.objects.bulk_create([
            LedgerEntry(
                merchant_id=payout.merchant_id,
                amount=payout.amount_paise,         # +X: release the hold
                type=LedgerEntryType.PAYOUT_RELEASE,
                reference_id=payout.id,
            ),
            LedgerEntry(
                merchant_id=payout.merchant_id,
                amount=-payout.amount_paise,        # -X: permanent outflow
                type=LedgerEntryType.PAYOUT_DEBIT,
                reference_id=payout.id,
            ),
        ])
        logger.info("Payout settled (success) id=%s", payout.id)


def settle_payout_failure(payout: Payout, reason: str) -> None:
    """
    Atomically: transition state to failed + release the hold.
    Net ledger effect: release(+X) cancels out hold(-X) → funds fully restored.
    """
    with transaction.atomic():
        payout.transition_to(PayoutState.FAILED)
        Payout.objects.filter(pk=payout.pk).update(failure_reason=reason)

        LedgerEntry.objects.create(
            merchant_id=payout.merchant_id,
            amount=payout.amount_paise,             # +X: reverse the hold
            type=LedgerEntryType.PAYOUT_RELEASE,
            reference_id=payout.id,
        )
        logger.info("Payout settled (failure) id=%s reason=%s", payout.id, reason)
