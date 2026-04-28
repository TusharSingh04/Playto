"""
Ledger balance invariant tests.
"""

import uuid
from django.test import TestCase

from apps.ledger.models import LedgerEntry, LedgerEntryType
from apps.ledger.queries import get_merchant_balance
from apps.merchants.models import Merchant


class TestLedgerBalance(TestCase):

    def setUp(self):
        self.merchant = Merchant.objects.create(name="Ledger Test", email="ledger@test.com")

    def _entry(self, amount, entry_type, ref=None):
        return LedgerEntry.objects.create(
            merchant=self.merchant,
            amount=amount,
            type=entry_type,
            reference_id=ref or uuid.uuid4(),
        )

    def test_zero_balance_on_empty_ledger(self):
        bal = get_merchant_balance(self.merchant.id)
        self.assertEqual(bal["available_paise"], 0)
        self.assertEqual(bal["held_paise"], 0)

    def test_credit_increases_available(self):
        self._entry(50_000, LedgerEntryType.CREDIT)
        bal = get_merchant_balance(self.merchant.id)
        self.assertEqual(bal["available_paise"], 50_000)
        self.assertEqual(bal["held_paise"], 0)

    def test_hold_reduces_available_increases_held(self):
        self._entry(50_000, LedgerEntryType.CREDIT)
        payout_id = uuid.uuid4()
        self._entry(-20_000, LedgerEntryType.PAYOUT_HOLD, payout_id)

        bal = get_merchant_balance(self.merchant.id)
        self.assertEqual(bal["available_paise"], 30_000)  # 50k - 20k hold
        self.assertEqual(bal["held_paise"], 20_000)

    def test_successful_settlement_correct_balance(self):
        """After hold + release + debit: available = credit - amount, held = 0."""
        self._entry(50_000, LedgerEntryType.CREDIT)
        payout_id = uuid.uuid4()
        self._entry(-20_000, LedgerEntryType.PAYOUT_HOLD, payout_id)
        # Settlement: release hold + permanent debit
        self._entry(20_000, LedgerEntryType.PAYOUT_RELEASE, payout_id)
        self._entry(-20_000, LedgerEntryType.PAYOUT_DEBIT, payout_id)

        bal = get_merchant_balance(self.merchant.id)
        self.assertEqual(bal["available_paise"], 30_000)  # 50k - 20k
        self.assertEqual(bal["held_paise"], 0)            # hold fully released

    def test_failed_settlement_releases_funds_fully(self):
        """After hold + release (failure): available = original credit, held = 0."""
        self._entry(50_000, LedgerEntryType.CREDIT)
        payout_id = uuid.uuid4()
        self._entry(-20_000, LedgerEntryType.PAYOUT_HOLD, payout_id)
        # Failure: only release
        self._entry(20_000, LedgerEntryType.PAYOUT_RELEASE, payout_id)

        bal = get_merchant_balance(self.merchant.id)
        self.assertEqual(bal["available_paise"], 50_000)  # fully restored
        self.assertEqual(bal["held_paise"], 0)

    def test_balance_never_goes_negative_invariant(self):
        """SUM of all ledger entries must never be negative for a valid merchant."""
        self._entry(10_000, LedgerEntryType.CREDIT)
        payout_id = uuid.uuid4()
        self._entry(-10_000, LedgerEntryType.PAYOUT_HOLD, payout_id)
        # At this point available = 0, held = 10000

        bal = get_merchant_balance(self.merchant.id)
        self.assertEqual(bal["available_paise"], 0)
        self.assertGreaterEqual(bal["available_paise"], 0)

    def test_multiple_payouts_balance(self):
        self._entry(100_000, LedgerEntryType.CREDIT)

        p1 = uuid.uuid4()
        p2 = uuid.uuid4()
        self._entry(-30_000, LedgerEntryType.PAYOUT_HOLD, p1)
        self._entry(-20_000, LedgerEntryType.PAYOUT_HOLD, p2)

        # p1 succeeds
        self._entry(30_000, LedgerEntryType.PAYOUT_RELEASE, p1)
        self._entry(-30_000, LedgerEntryType.PAYOUT_DEBIT, p1)

        # p2 fails
        self._entry(20_000, LedgerEntryType.PAYOUT_RELEASE, p2)

        bal = get_merchant_balance(self.merchant.id)
        self.assertEqual(bal["available_paise"], 70_000)  # 100k - 30k success
        self.assertEqual(bal["held_paise"], 0)
