"""
State machine tests: verify all illegal transitions are rejected.
"""

import uuid
import pytest
from django.test import TestCase

from apps.merchants.models import Merchant, BankAccount
from apps.payouts.exceptions import PayoutTransitionError
from apps.payouts.models import Payout, PayoutState
from apps.ledger.models import LedgerEntry, LedgerEntryType


def make_payout(state=PayoutState.PENDING):
    merchant = Merchant.objects.create(name="SM Test", email=f"sm{uuid.uuid4().hex[:6]}@test.com")
    ba = BankAccount.objects.create(
        merchant=merchant,
        account_number="111000111000",
        ifsc_code="TEST0000003",
        account_holder_name="SM Test",
    )
    return Payout.objects.create(
        merchant=merchant,
        bank_account=ba,
        amount_paise=10_000,
        state=state,
    )


class TestStateMachine(TestCase):

    def test_pending_to_processing_allowed(self):
        p = make_payout(PayoutState.PENDING)
        p.transition_to(PayoutState.PROCESSING)
        p.refresh_from_db()
        self.assertEqual(p.state, PayoutState.PROCESSING)

    def test_processing_to_completed_allowed(self):
        p = make_payout(PayoutState.PROCESSING)
        p.transition_to(PayoutState.COMPLETED)
        p.refresh_from_db()
        self.assertEqual(p.state, PayoutState.COMPLETED)

    def test_processing_to_failed_allowed(self):
        p = make_payout(PayoutState.PROCESSING)
        p.transition_to(PayoutState.FAILED)
        p.refresh_from_db()
        self.assertEqual(p.state, PayoutState.FAILED)

    def test_completed_to_anything_rejected(self):
        p = make_payout(PayoutState.COMPLETED)
        with self.assertRaises(PayoutTransitionError):
            p.transition_to(PayoutState.PROCESSING)
        with self.assertRaises(PayoutTransitionError):
            p.transition_to(PayoutState.FAILED)
        with self.assertRaises(PayoutTransitionError):
            p.transition_to(PayoutState.PENDING)

    def test_failed_to_completed_rejected(self):
        p = make_payout(PayoutState.FAILED)
        with self.assertRaises(PayoutTransitionError):
            p.transition_to(PayoutState.COMPLETED)

    def test_pending_to_completed_rejected(self):
        p = make_payout(PayoutState.PENDING)
        with self.assertRaises(PayoutTransitionError):
            p.transition_to(PayoutState.COMPLETED)

    def test_optimistic_lock_detects_concurrent_modification(self):
        """
        If two code paths try to transition the same payout simultaneously,
        only one succeeds. The second gets PayoutTransitionError.
        """
        p = make_payout(PayoutState.PENDING)

        # First transition succeeds
        p.transition_to(PayoutState.PROCESSING)
        self.assertEqual(p.state, PayoutState.PROCESSING)

        # Simulate a stale reference that still thinks state is PENDING
        stale = Payout(pk=p.pk, state=PayoutState.PENDING, merchant_id=p.merchant_id, bank_account_id=p.bank_account_id, amount_paise=p.amount_paise)
        with self.assertRaises(PayoutTransitionError):
            stale.transition_to(PayoutState.PROCESSING)
