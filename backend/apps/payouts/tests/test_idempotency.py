"""
Idempotency tests.

Key properties verified:
1. Same idempotency key + same merchant → exactly one payout created.
2. Response from second call is identical to first call's payout.
3. In-flight duplicate is rejected with IdempotencyConflictError.
4. Different merchants with same key string → two separate payouts (keys are merchant-scoped).
5. Expired key is treated as a new request.
"""

import threading
import time
import uuid
from datetime import timedelta
from unittest.mock import patch

import pytest
from django.test import TransactionTestCase
from django.utils import timezone

from apps.ledger.models import LedgerEntry, LedgerEntryType
from apps.merchants.models import BankAccount, Merchant
from apps.payouts.exceptions import IdempotencyConflictError, InsufficientFundsError
from apps.payouts.models import IdempotencyKey, Payout
from apps.payouts.service import create_payout


def make_merchant(name_suffix=""):
    merchant = Merchant.objects.create(
        name=f"Test Merchant{name_suffix}",
        email=f"test{name_suffix}@example.com",
    )
    bank_account = BankAccount.objects.create(
        merchant=merchant,
        account_number="999888777666",
        ifsc_code="TEST0000002",
        account_holder_name=merchant.name,
    )
    LedgerEntry.objects.create(
        merchant=merchant,
        amount=1_000_000,  # ₹10,000
        type=LedgerEntryType.CREDIT,
        reference_id=uuid.uuid4(),
    )
    return merchant, bank_account


class TestIdempotency(TransactionTestCase):

    def test_same_key_same_merchant_returns_same_payout(self):
        merchant, bank_account = make_merchant("_idem1")
        key = str(uuid.uuid4())

        payout1, created1 = create_payout(
            merchant_id=merchant.id,
            bank_account_id=bank_account.id,
            amount_paise=50_000,
            idempotency_key_str=key,
        )
        payout2, created2 = create_payout(
            merchant_id=merchant.id,
            bank_account_id=bank_account.id,
            amount_paise=50_000,
            idempotency_key_str=key,
        )

        self.assertTrue(created1, "First call should create the payout")
        self.assertFalse(created2, "Second call should be an idempotent replay")
        self.assertEqual(payout1.id, payout2.id, "Both calls must return the same payout")

        # Only ONE payout in DB
        self.assertEqual(
            Payout.objects.filter(merchant=merchant).count(),
            1,
            "Exactly one payout must exist in the database",
        )

        # Only ONE hold entry
        self.assertEqual(
            LedgerEntry.objects.filter(
                merchant=merchant,
                type=LedgerEntryType.PAYOUT_HOLD,
            ).count(),
            1,
            "Exactly one hold ledger entry must exist",
        )

    def test_different_keys_create_different_payouts(self):
        merchant, bank_account = make_merchant("_idem2")

        key1 = str(uuid.uuid4())
        key2 = str(uuid.uuid4())

        p1, _ = create_payout(
            merchant_id=merchant.id,
            bank_account_id=bank_account.id,
            amount_paise=10_000,
            idempotency_key_str=key1,
        )
        p2, _ = create_payout(
            merchant_id=merchant.id,
            bank_account_id=bank_account.id,
            amount_paise=10_000,
            idempotency_key_str=key2,
        )

        self.assertNotEqual(p1.id, p2.id)
        self.assertEqual(Payout.objects.filter(merchant=merchant).count(), 2)

    def test_same_key_different_merchants_creates_two_payouts(self):
        """Idempotency keys are scoped per merchant."""
        m1, ba1 = make_merchant("_idem3a")
        m2, ba2 = make_merchant("_idem3b")
        shared_key = str(uuid.uuid4())

        p1, c1 = create_payout(
            merchant_id=m1.id,
            bank_account_id=ba1.id,
            amount_paise=10_000,
            idempotency_key_str=shared_key,
        )
        p2, c2 = create_payout(
            merchant_id=m2.id,
            bank_account_id=ba2.id,
            amount_paise=10_000,
            idempotency_key_str=shared_key,
        )

        self.assertTrue(c1)
        self.assertTrue(c2)
        self.assertNotEqual(p1.id, p2.id)

    def test_in_flight_duplicate_raises_conflict(self):
        """
        Simulate a key that is IN_PROGRESS (another request is still processing it).
        Must raise IdempotencyConflictError, not create a duplicate payout.
        """
        merchant, bank_account = make_merchant("_idem4")
        key = str(uuid.uuid4())

        # Manually create an in-progress idempotency record (simulating a concurrent request)
        IdempotencyKey.objects.create(
            merchant=merchant,
            key=key,
            status=IdempotencyKey.Status.IN_PROGRESS,
            expires_at=timezone.now() + timedelta(hours=24),
        )

        with self.assertRaises(IdempotencyConflictError):
            create_payout(
                merchant_id=merchant.id,
                bank_account_id=bank_account.id,
                amount_paise=10_000,
                idempotency_key_str=key,
            )

        # No payout should have been created
        self.assertEqual(Payout.objects.filter(merchant=merchant).count(), 0)

    def test_expired_key_creates_new_payout(self):
        """An expired idempotency key must not block a new payout creation."""
        merchant, bank_account = make_merchant("_idem5")
        key = str(uuid.uuid4())

        # Create an expired complete key
        idem = IdempotencyKey.objects.create(
            merchant=merchant,
            key=key,
            status=IdempotencyKey.Status.COMPLETE,
            expires_at=timezone.now() - timedelta(hours=1),  # already expired
        )

        # Should create a new payout, not replay the old one
        payout, created = create_payout(
            merchant_id=merchant.id,
            bank_account_id=bank_account.id,
            amount_paise=10_000,
            idempotency_key_str=key,
        )

        self.assertTrue(created, "Expired key should allow a fresh payout")
        self.assertEqual(Payout.objects.filter(merchant=merchant).count(), 1)

    def test_insufficient_funds_does_not_store_idempotency_key(self):
        """
        A failed balance check must NOT leave a dangling idempotency key.
        The merchant must be able to retry with the same key after topping up.
        """
        merchant, bank_account = make_merchant("_idem6")
        key = str(uuid.uuid4())

        with self.assertRaises(InsufficientFundsError):
            create_payout(
                merchant_id=merchant.id,
                bank_account_id=bank_account.id,
                amount_paise=99_999_999,  # way more than available
                idempotency_key_str=key,
            )

        # Key must NOT be stored
        self.assertFalse(
            IdempotencyKey.objects.filter(merchant=merchant, key=key).exists(),
            "No idempotency key should be stored for a funds-rejection",
        )
