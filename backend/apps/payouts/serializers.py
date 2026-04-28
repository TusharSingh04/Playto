import uuid
from rest_framework import serializers
from apps.payouts.models import Payout


class CreatePayoutSerializer(serializers.Serializer):
    amount_paise = serializers.IntegerField(min_value=1)
    bank_account_id = serializers.UUIDField()

    def validate_amount_paise(self, value):
        # Minimum payout: ₹1 (100 paise)
        if value < 100:
            raise serializers.ValidationError("Minimum payout amount is ₹1 (100 paise).")
        return value


class PayoutSerializer(serializers.ModelSerializer):
    amount_rupees = serializers.SerializerMethodField()
    bank_account_last4 = serializers.SerializerMethodField()

    class Meta:
        model = Payout
        fields = [
            "id",
            "merchant",
            "bank_account",
            "bank_account_last4",
            "amount_paise",
            "amount_rupees",
            "state",
            "attempts",
            "failure_reason",
            "created_at",
            "updated_at",
        ]

    def get_amount_rupees(self, obj):
        return f"{obj.amount_paise / 100:.2f}"

    def get_bank_account_last4(self, obj):
        return obj.bank_account.account_number[-4:]
