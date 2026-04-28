"""
Concurrency test: two simultaneous payout requests for a merchant with
insufficient balance to cover both.

Exactly ONE must succeed. ONE must fail with InsufficientFundsError.
No double-hold, no negative balance.

Strategy:
  - We use Python threading (not multiprocessing) to simulate concurrent DB connections.
  - Each thread opens its own Django DB connection (Django creates a new connection
    per thread automatically).
  - We use a threading.Barrier to synchronise both threads so they hit the
    database at the same moment, maximising the chance of a race.
  - After both threads complete, we assert ledger invariants hold.
"""

import threading
import uuid
import pytest

from django.db import connection
from django.test import TransactionTestCase

from apps.ledger.models import LedgerEntry, LedgerEntryType
from apps.ledger.queries import get_merchant_balance
from apps.merchants.models import BankAccount, Merchant
from apps.payouts.exceptions import InsufficientFundsError
from apps.payouts.models import Payout, PayoutState
from apps.payouts.service import create_payout


class TestConcurrentPayouts(TransactionTestCase):
    """
    Must use TransactionTestCase (not TestCase) because:
    - TestCase wraps everything in a transaction and rolls back at the end.
    - Concurrent threads cannot see each other's writes inside that wrapping
      transaction, so SELECT FOR UPDATE cannot correctly serialize them.
    - TransactionTestCase uses real transactions and truncates tables between runs.
    """

    def setUp(self):
        self.merchant = Merchant.objects.create(
            id=uuid.UUID("aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa"),
            name="Concurrent Test Merchant",
            email="concurrent@test.com",
        )
        self.bank_account = BankAccount.objects.create(
            merchant=self.merchant,
            account_number="111222333444",
            ifsc_code="TEST0000001",
            account_holder_name="Concurrent Test Merchant",
        )
        # Seed ₹100 (10,000 paise)
        LedgerEntry.objects.create(
            merchant=self.merchant,
            amount=10_000,
            type=LedgerEntryType.CREDIT,
            reference_id=uuid.uuid4(),
        )

    def tearDown(self):
        connection.close()

    def test_only_one_of_two_concurrent_payouts_succeeds(self):
        """
        Two threads simultaneously request ₹60 each against a ₹100 balance.
        Exactly one must succeed; the other must raise InsufficientFundsError.
        """
        results = []
        errors = []
        barrier = threading.Barrier(2)

        def attempt_payout(idempotency_key):
            barrier.wait()  # Both threads reach this point before either proceeds
            try:
                payout, created = create_payout(
                    merchant_id=self.merchant.id,
                    bank_account_id=self.bank_account.id,
                    amount_paise=6_000,  # ₹60
                    idempotency_key_str=str(idempotency_key),
                )
                results.append(("success", payout.id))
            except InsufficientFundsError as exc:
                errors.append(("insufficient_funds", str(exc)))
            except Exception as exc:
                errors.append(("unexpected_error", str(exc)))
            finally:
                # Each thread must close its own connection
                connection.close()

        key1 = uuid.uuid4()
        key2 = uuid.uuid4()

        t1 = threading.Thread(target=attempt_payout, args=(key1,))
        t2 = threading.Thread(target=attempt_payout, args=(key2,))
        t1.start()
        t2.start()
        t1.join(timeout=10)
        t2.join(timeout=10)

        # ── Assertions ────────────────────────────────────────────────────────
        total_outcomes = len(results) + len(errors)
        self.assertEqual(total_outcomes, 2, f"Expected 2 outcomes, got: results={results} errors={errors}")

        # Exactly one success, one failure
        self.assertEqual(len(results), 1, f"Expected exactly 1 success, got: {results}")
        self.assertEqual(len(errors), 1, f"Expected exactly 1 failure, got: {errors}")
        self.assertEqual(errors[0][0], "insufficient_funds")

        # Ledger invariant: available balance must be ≥ 0
        balance = get_merchant_balance(self.merchant.id)
        self.assertGreaterEqual(
            balance["available_paise"], 0,
            f"Available balance went negative: {balance['available_paise']}"
        )

        # Exactly one payout in DB
        payouts = Payout.objects.filter(merchant=self.merchant, state=PayoutState.PENDING)
        self.assertEqual(payouts.count(), 1, "Expected exactly 1 pending payout")

        # Exactly one hold entry in ledger
        holds = LedgerEntry.objects.filter(
            merchant=self.merchant,
            type=LedgerEntryType.PAYOUT_HOLD,
        )
        self.assertEqual(holds.count(), 1, "Expected exactly 1 hold ledger entry")

        # The hold amount equals the successful payout amount
        hold = holds.first()
        self.assertEqual(hold.amount, -6_000)

    def test_sequential_payouts_both_succeed_when_sufficient_funds(self):
        """
        Sanity check: two sequential ₹40 payouts against ₹100 both succeed.
        """
        p1, _ = create_payout(
            merchant_id=self.merchant.id,
            bank_account_id=self.bank_account.id,
            amount_paise=4_000,
            idempotency_key_str=str(uuid.uuid4()),
        )
        p2, _ = create_payout(
            merchant_id=self.merchant.id,
            bank_account_id=self.bank_account.id,
            amount_paise=4_000,
            idempotency_key_str=str(uuid.uuid4()),
        )
        balance = get_merchant_balance(self.merchant.id)
        self.assertEqual(balance["available_paise"], 2_000)  # ₹20 left
        self.assertEqual(balance["held_paise"], 8_000)       # ₹80 held

    def test_third_payout_fails_when_balance_exhausted(self):
        """
        After two ₹40 holds against ₹100, a third ₹30 payout must fail.
        """
        create_payout(
            merchant_id=self.merchant.id,
            bank_account_id=self.bank_account.id,
            amount_paise=4_000,
            idempotency_key_str=str(uuid.uuid4()),
        )
        create_payout(
            merchant_id=self.merchant.id,
            bank_account_id=self.bank_account.id,
            amount_paise=4_000,
            idempotency_key_str=str(uuid.uuid4()),
        )
        with self.assertRaises(InsufficientFundsError):
            create_payout(
                merchant_id=self.merchant.id,
                bank_account_id=self.bank_account.id,
                amount_paise=3_000,
                idempotency_key_str=str(uuid.uuid4()),
            )
