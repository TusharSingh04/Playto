import uuid
from django.conf import settings
from django.db import models


class Merchant(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    name = models.CharField(max_length=255)
    email = models.EmailField(unique=True)
    # Auth linkage: every Merchant maps to exactly one Django User. Views
    # derive merchant identity from request.user — body-supplied merchant_id
    # is no longer trusted. Nullable for backfill of pre-auth seed data.
    auth_user = models.OneToOneField(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="merchant",
        null=True,
        blank=True,
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "merchants"

    def __str__(self):
        return self.name


class BankAccount(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    merchant = models.ForeignKey(Merchant, on_delete=models.PROTECT, related_name="bank_accounts")
    account_number = models.CharField(max_length=30)
    ifsc_code = models.CharField(max_length=11)
    account_holder_name = models.CharField(max_length=255)
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "bank_accounts"
        unique_together = [("merchant", "account_number", "ifsc_code")]

    def __str__(self):
        return f"{self.account_holder_name} — {self.account_number[-4:].rjust(len(self.account_number), '*')}"
