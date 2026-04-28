from rest_framework.response import Response
from rest_framework.views import APIView

from apps.ledger.queries import get_merchant_ledger_history
from apps.ledger.serializers import LedgerEntrySerializer
from apps.merchants.permissions import require_owned_merchant


class MerchantLedgerView(APIView):
    """
    GET /api/v1/merchants/<merchant_id>/ledger

    Authorization: only the merchant's own user may read its ledger.
    """

    def get(self, request, merchant_id):
        merchant = require_owned_merchant(request, merchant_id)
        entries = get_merchant_ledger_history(merchant.id)
        return Response(LedgerEntrySerializer(entries, many=True).data)
