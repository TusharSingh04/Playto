import uuid
from django.db import models
from django.utils import timezone


class PayoutState(models.TextChoices):
    PENDING = "pending", "Pending"
    PROCESSING = "processing", "Processing"
    COMPLETED = "completed", "Completed"
    FAILED = "failed", "Failed"


# State machine definition: state → allowed next states
VALID_TRANSITIONS: dict[str, list[str]] = {
    PayoutState.PENDING: [PayoutState.PROCESSING],
    PayoutState.PROCESSING: [PayoutState.COMPLETED, PayoutState.FAILED],
    PayoutState.COMPLETED: [],
    PayoutState.FAILED: [],
}


class Payout(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    merchant = models.ForeignKey(
        "merchants.Merchant", on_delete=models.PROTECT, related_name="payouts"
    )
    bank_account = models.ForeignKey(
        "merchants.BankAccount", on_delete=models.PROTECT, related_name="payouts"
    )
    amount_paise = models.BigIntegerField()
    state = models.CharField(max_length=20, choices=PayoutState.choices, default=PayoutState.PENDING, db_index=True)
    attempts = models.PositiveSmallIntegerField(default=0)
    # Denormalised for worker scheduling; cleared once terminal state reached
    processing_started_at = models.DateTimeField(null=True, blank=True)
    failure_reason = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "payouts"
        indexes = [
            models.Index(fields=["merchant", "state"]),
            models.Index(fields=["state", "processing_started_at"]),
        ]

    def __str__(self):
        return f"Payout {self.id} [{self.state}] {self.amount_paise}p"

    def transition_to(self, new_state: str) -> "Payout":
        """
        Attempt a state transition using an optimistic-locking UPDATE.

        Uses filter(state=current_state) so a concurrent transition that
        already moved this payout to another state will produce 0 rows updated,
        raising PayoutTransitionError instead of silently succeeding.
        """
        from apps.payouts.exceptions import PayoutTransitionError

        allowed = VALID_TRANSITIONS.get(self.state, [])
        if new_state not in allowed:
            raise PayoutTransitionError(
                f"Cannot transition payout {self.id} from '{self.state}' to '{new_state}'. "
                f"Allowed: {allowed}"
            )

        extra_fields: dict = {}
        if new_state == PayoutState.PROCESSING:
            extra_fields["processing_started_at"] = timezone.now()
        elif new_state in (PayoutState.COMPLETED, PayoutState.FAILED):
            extra_fields["processing_started_at"] = None

        updated = Payout.objects.filter(pk=self.pk, state=self.state).update(
            state=new_state, **extra_fields
        )
        if updated == 0:
            raise PayoutTransitionError(
                f"Concurrent modification: payout {self.id} was already moved away from '{self.state}'."
            )

        self.state = new_state
        for field, value in extra_fields.items():
            setattr(self, field, value)
        return self


class IdempotencyKey(models.Model):
    """
    Per-merchant idempotency store scoped to 24 hours.

    Uniqueness is enforced at DB level via (merchant, key).
    The response_snapshot stores the exact serialised response so
    replayed requests get bit-for-bit identical responses.
    """

    class Status(models.TextChoices):
        IN_PROGRESS = "in_progress", "In Progress"
        COMPLETE = "complete", "Complete"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    merchant = models.ForeignKey(
        "merchants.Merchant", on_delete=models.PROTECT, related_name="idempotency_keys"
    )
    key = models.CharField(max_length=255, db_index=True)
    status = models.CharField(max_length=20, choices=Status.choices, default=Status.IN_PROGRESS)
    # Full serialised response payload stored here
    response_snapshot = models.JSONField(null=True, blank=True)
    payout = models.OneToOneField(
        Payout, on_delete=models.SET_NULL, null=True, blank=True, related_name="idempotency_record"
    )
    expires_at = models.DateTimeField(db_index=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "idempotency_keys"
        unique_together = [("merchant", "key")]

    def __str__(self):
        return f"IdempotencyKey {self.key} [{self.status}]"
