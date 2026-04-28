"""
All balance computations happen in the database via aggregation.
No Python-side arithmetic on ledger rows.

Balance invariants:
  Available balance = SUM(amount) over all ledger entries for a merchant
  Held balance      = -SUM(amount) WHERE type IN ('payout_hold', 'payout_release')

The signs work because:
  credit          → +X   → increases available
  payout_hold     → -X   → decreases available, increases held
  payout_release  → +X   → increases available (reverses a hold); decreases held
  payout_debit    → -X   → permanent outflow (paired with release on success)

So: SUM(all) gives net funds remaining.
And: -SUM(hold types) gives the net unreleased hold balance.
"""

from django.db import models
from django.db.models import Sum, Value
from django.db.models.functions import Coalesce

from apps.ledger.models import LedgerEntry, LedgerEntryType


def get_merchant_balance(merchant_id) -> dict:
    """
    Returns a dict with 'available_paise' and 'held_paise'.
    Both values come directly from a single database aggregate pass.
    Called inside a SELECT FOR UPDATE transaction when used for payout creation.
    """
    # Single query over the ledger for this merchant
    result = LedgerEntry.objects.filter(merchant_id=merchant_id).aggregate(
        available_paise=Coalesce(Sum("amount"), Value(0)),
        held_paise=Coalesce(
            # Hold entries are negative; release entries are positive.
            # Net held = -(sum of hold+release amounts)
            -Sum(
                "amount",
                filter=models.Q(
                    type__in=[LedgerEntryType.PAYOUT_HOLD, LedgerEntryType.PAYOUT_RELEASE]
                ),
            ),
            Value(0),
        ),
    )
    return result


def get_merchant_ledger_history(merchant_id, limit: int = 50) -> models.QuerySet:
    return (
        LedgerEntry.objects.filter(merchant_id=merchant_id)
        .order_by("-created_at")
        .select_related("merchant")[:limit]
    )
