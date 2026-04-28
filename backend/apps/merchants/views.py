from rest_framework import generics
from apps.merchants.models import Merchant
from apps.merchants.serializers import MerchantSerializer
from apps.ledger.queries import get_merchant_balance
from rest_framework.response import Response
from rest_framework.views import APIView
from django.shortcuts import get_object_or_404


class MerchantListView(generics.ListAPIView):
    queryset = Merchant.objects.prefetch_related("bank_accounts").order_by("name")
    serializer_class = MerchantSerializer


class MerchantDetailView(generics.RetrieveAPIView):
    queryset = Merchant.objects.prefetch_related("bank_accounts")
    serializer_class = MerchantSerializer
    lookup_field = "pk"


class MerchantBalanceView(APIView):
    def get(self, request, merchant_id):
        merchant = get_object_or_404(Merchant, pk=merchant_id)
        balance = get_merchant_balance(merchant.id)
        return Response({
            "merchant_id": str(merchant.id),
            "merchant_name": merchant.name,
            "available_paise": balance["available_paise"],
            "held_paise": balance["held_paise"],
            "available_rupees": f"{balance['available_paise'] / 100:.2f}",
            "held_rupees": f"{balance['held_paise'] / 100:.2f}",
        })
