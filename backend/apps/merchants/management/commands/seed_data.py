"""
Management command: python manage.py seed_data

Creates 3 merchants with bank accounts and realistic credit history.
Safe to run multiple times (idempotent via get_or_create).
"""

import uuid
from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand
from django.db import transaction
from rest_framework.authtoken.models import Token
from apps.merchants.models import Merchant, BankAccount
from apps.ledger.models import LedgerEntry, LedgerEntryType

User = get_user_model()

# Default password for seeded merchants. Override via env if you must, but
# this command is dev/seed-only and the README explicitly says "rotate before
# any non-local deployment".
SEED_PASSWORD = "playto-dev-password"


SEED_MERCHANTS = [
    {
        "id": "11111111-1111-1111-1111-111111111111",
        "name": "Acme Retail Pvt Ltd",
        "email": "acme@example.com",
        "username": "acme",
        "bank_accounts": [
            {
                "id": "aaaa1111-0000-0000-0000-000000000001",
                "account_number": "123456789012",
                "ifsc_code": "HDFC0001234",
                "account_holder_name": "Acme Retail Pvt Ltd",
            }
        ],
        # Total credit: ₹50,000 (5,000,000 paise)
        "credits": [
            {"amount": 2_000_000, "ref": "ext-txn-acme-001"},  # ₹20,000
            {"amount": 1_500_000, "ref": "ext-txn-acme-002"},  # ₹15,000
            {"amount": 1_500_000, "ref": "ext-txn-acme-003"},  # ₹15,000
        ],
    },
    {
        "id": "22222222-2222-2222-2222-222222222222",
        "name": "Bharat Electronics",
        "email": "bharat@example.com",
        "username": "bharat",
        "bank_accounts": [
            {
                "id": "bbbb2222-0000-0000-0000-000000000001",
                "account_number": "987654321098",
                "ifsc_code": "ICIC0005678",
                "account_holder_name": "Bharat Electronics",
            }
        ],
        # Total credit: ₹20,000 (2,000,000 paise)
        "credits": [
            {"amount": 1_000_000, "ref": "ext-txn-bharat-001"},  # ₹10,000
            {"amount": 1_000_000, "ref": "ext-txn-bharat-002"},  # ₹10,000
        ],
    },
    {
        "id": "33333333-3333-3333-3333-333333333333",
        "name": "Chennai Crafts",
        "email": "chennai@example.com",
        "username": "chennai",
        "bank_accounts": [
            {
                "id": "cccc3333-0000-0000-0000-000000000001",
                "account_number": "555444333222",
                "ifsc_code": "SBIN0009012",
                "account_holder_name": "Chennai Crafts",
            }
        ],
        # Total credit: ₹5,000 (500,000 paise) — small merchant for edge case testing
        "credits": [
            {"amount": 300_000, "ref": "ext-txn-chennai-001"},  # ₹3,000
            {"amount": 200_000, "ref": "ext-txn-chennai-002"},  # ₹2,000
        ],
    },
]


class Command(BaseCommand):
    help = "Seed merchants, bank accounts, and ledger credits"

    @transaction.atomic
    def handle(self, *args, **options):
        for m_data in SEED_MERCHANTS:
            # ── Auth user (one User per Merchant) ────────────────────────────
            user, user_created = User.objects.get_or_create(
                username=m_data["username"],
                defaults={"email": m_data["email"]},
            )
            if user_created:
                user.set_password(SEED_PASSWORD)
                user.save()
                self.stdout.write(f"  Created user: {user.username} (password: {SEED_PASSWORD})")

            # Issue a token so the frontend / curl can hit the API immediately
            token, _ = Token.objects.get_or_create(user=user)

            # ── Merchant linked to the user ──────────────────────────────────
            merchant, created = Merchant.objects.get_or_create(
                id=m_data["id"],
                defaults={
                    "name": m_data["name"],
                    "email": m_data["email"],
                    "auth_user": user,
                },
            )
            if created:
                self.stdout.write(
                    f"  Created merchant: {merchant.name}  token={token.key}"
                )
            else:
                # Backfill auth_user on a previously seeded merchant
                if merchant.auth_user_id is None:
                    merchant.auth_user = user
                    merchant.save(update_fields=["auth_user"])
                self.stdout.write(
                    f"  Merchant already exists: {merchant.name}  token={token.key}"
                )

            for ba_data in m_data["bank_accounts"]:
                BankAccount.objects.get_or_create(
                    id=ba_data["id"],
                    defaults={
                        "merchant": merchant,
                        "account_number": ba_data["account_number"],
                        "ifsc_code": ba_data["ifsc_code"],
                        "account_holder_name": ba_data["account_holder_name"],
                    },
                )

            for credit in m_data["credits"]:
                ref = uuid.UUID(
                    # Deterministic UUID from the reference string
                    str(uuid.uuid5(uuid.NAMESPACE_DNS, credit["ref"]))
                )
                if not LedgerEntry.objects.filter(reference_id=ref).exists():
                    LedgerEntry.objects.create(
                        merchant=merchant,
                        amount=credit["amount"],
                        type=LedgerEntryType.CREDIT,
                        reference_id=ref,
                    )
                    self.stdout.write(
                        f"    + Credit {credit['amount']} paise (₹{credit['amount']/100:.0f}) [{credit['ref']}]"
                    )

        self.stdout.write(self.style.SUCCESS("\nSeed complete."))
