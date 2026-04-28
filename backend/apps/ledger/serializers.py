from rest_framework import serializers
from apps.ledger.models import LedgerEntry


class LedgerEntrySerializer(serializers.ModelSerializer):
    amount_rupees = serializers.SerializerMethodField()

    class Meta:
        model = LedgerEntry
        fields = ["id", "merchant", "amount", "amount_rupees", "type", "reference_id", "created_at"]

    def get_amount_rupees(self, obj):
        return f"{obj.amount / 100:.2f}"
