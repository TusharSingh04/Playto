from rest_framework import generics
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.ledger.queries import get_merchant_balance
from apps.merchants.models import Merchant
from apps.merchants.permissions import require_owned_merchant
from apps.merchants.serializers import MerchantSerializer


class MerchantListView(generics.ListAPIView):
    """
    GET /api/v1/merchants/

    Scoped to the authenticated user — returns only the requesting user's
    own merchant. Listing all merchants would leak tenant existence.
    """

    serializer_class = MerchantSerializer

    def get_queryset(self):
        merchant = getattr(self.request.user, "merchant", None)
        if merchant is None:
            return Merchant.objects.none()
        return Merchant.objects.filter(pk=merchant.pk).prefetch_related("bank_accounts")


class MerchantDetailView(generics.RetrieveAPIView):
    serializer_class = MerchantSerializer
    lookup_field = "pk"

    def get_object(self):
        return require_owned_merchant(self.request, self.kwargs["pk"])


class MerchantBalanceView(APIView):
    def get(self, request, merchant_id):
        merchant = require_owned_merchant(request, merchant_id)
        balance = get_merchant_balance(merchant.id)
        return Response({
            "merchant_id": str(merchant.id),
            "merchant_name": merchant.name,
            "available_paise": balance["available_paise"],
            "held_paise": balance["held_paise"],
            "available_rupees": f"{balance['available_paise'] / 100:.2f}",
            "held_rupees": f"{balance['held_paise'] / 100:.2f}",
        })
