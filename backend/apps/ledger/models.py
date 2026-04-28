import uuid
from django.db import models


class LedgerEntryType(models.TextChoices):
    CREDIT = "credit", "Credit"
    PAYOUT_HOLD = "payout_hold", "Payout Hold"
    PAYOUT_DEBIT = "payout_debit", "Payout Debit"
    PAYOUT_RELEASE = "payout_release", "Payout Release"


class LedgerEntry(models.Model):
    """
    Append-only ledger. Single source of truth for all balances.

    Signed amount convention:
      credit        → +X  (funds received)
      payout_hold   → -X  (funds reserved when payout is created)
      payout_release→ +X  (hold reversed on failure, or pre-step on success)
      payout_debit  → -X  (permanent outflow on success, paired with release)

    Available balance  = SUM(amount) for all entries
    Held balance       = -SUM(amount) WHERE type IN ('payout_hold','payout_release')

    This means: completed payout produces hold(-X) + release(+X) + debit(-X) = net -X ✓
                failed payout produces hold(-X) + release(+X) = net 0 ✓
                pending payout produces hold(-X) = net -X from available, +X in held ✓
    """

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    merchant = models.ForeignKey(
        "merchants.Merchant", on_delete=models.PROTECT, related_name="ledger_entries"
    )
    # Signed integer in paise. NEVER store rupees or floats.
    amount = models.BigIntegerField()
    type = models.CharField(max_length=20, choices=LedgerEntryType.choices)
    # Points to Payout.id for hold/debit/release rows; external ref for credit rows
    reference_id = models.UUIDField(db_index=True)
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)

    class Meta:
        db_table = "ledger_entries"
        # Enforce append-only at DB level: no update permission granted to app user in prod
        indexes = [
            models.Index(fields=["merchant", "created_at"]),
            models.Index(fields=["merchant", "type"]),
        ]

    def __str__(self):
        return f"{self.type} {self.amount} paise (merchant={self.merchant_id})"
