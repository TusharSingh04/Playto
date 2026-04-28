from django.shortcuts import get_object_or_404
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.ledger.queries import get_merchant_ledger_history
from apps.ledger.serializers import LedgerEntrySerializer
from apps.merchants.models import Merchant


class MerchantLedgerView(APIView):
    """
    GET /api/v1/merchants/<merchant_id>/ledger
    """

    def get(self, request, merchant_id):
        merchant = get_object_or_404(Merchant, pk=merchant_id)
        entries = get_merchant_ledger_history(merchant.id)
        return Response(LedgerEntrySerializer(entries, many=True).data)
