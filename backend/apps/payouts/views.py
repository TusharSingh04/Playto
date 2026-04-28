import uuid
import logging

from django.shortcuts import get_object_or_404
from rest_framework import status
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.merchants.models import Merchant
from apps.payouts.models import Payout
from apps.payouts.serializers import CreatePayoutSerializer, PayoutSerializer
from apps.payouts.service import create_payout
from apps.payouts.tasks import process_payout

logger = logging.getLogger(__name__)


class PayoutCreateView(APIView):
    """
    POST /api/v1/payouts

    Required header: Idempotency-Key (UUID)

    Creates a payout atomically with a ledger hold.
    Enqueues async Celery task for processing.
    """

    def post(self, request):
        # ── Validate idempotency key ──────────────────────────────────────────
        raw_key = request.headers.get("Idempotency-Key", "").strip()
        if not raw_key:
            return Response(
                {"error": "missing_header", "detail": "Idempotency-Key header is required."},
                status=status.HTTP_400_BAD_REQUEST,
            )
        try:
            uuid.UUID(raw_key)  # Must be a valid UUID
        except ValueError:
            return Response(
                {"error": "invalid_header", "detail": "Idempotency-Key must be a valid UUID."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        # ── Validate request body ─────────────────────────────────────────────
        # merchant_id comes from request body (no auth layer in this demo)
        merchant_id_raw = request.data.get("merchant_id")
        if not merchant_id_raw:
            return Response(
                {"error": "missing_field", "detail": "merchant_id is required."},
                status=status.HTTP_400_BAD_REQUEST,
            )
        try:
            merchant_id = uuid.UUID(str(merchant_id_raw))
        except ValueError:
            return Response(
                {"error": "invalid_field", "detail": "merchant_id must be a valid UUID."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        serializer = CreatePayoutSerializer(data=request.data)
        if not serializer.is_valid():
            return Response(
                {"error": "validation_error", "detail": serializer.errors},
                status=status.HTTP_400_BAD_REQUEST,
            )

        # ── Core payout creation (service handles all locking + atomicity) ────
        payout, created = create_payout(
            merchant_id=merchant_id,
            bank_account_id=serializer.validated_data["bank_account_id"],
            amount_paise=serializer.validated_data["amount_paise"],
            idempotency_key_str=raw_key,
        )

        payout_data = PayoutSerializer(payout).data

        # Store response snapshot on the idempotency key for future replays
        if created:
            try:
                from apps.payouts.models import IdempotencyKey
                IdempotencyKey.objects.filter(
                    merchant_id=merchant_id, key=raw_key
                ).update(response_snapshot=payout_data)
            except Exception:
                pass  # Non-fatal; snapshot is best-effort

            # Enqueue async processing
            process_payout.delay(str(payout.id))
            logger.info("Enqueued process_payout for %s", payout.id)

        response_status = status.HTTP_201_CREATED if created else status.HTTP_200_OK
        return Response(payout_data, status=response_status)


class PayoutListView(APIView):
    """
    GET /api/v1/merchants/<merchant_id>/payouts
    """

    def get(self, request, merchant_id):
        merchant = get_object_or_404(Merchant, pk=merchant_id)
        payouts = (
            Payout.objects.filter(merchant=merchant)
            .select_related("bank_account")
            .order_by("-created_at")[:100]
        )
        return Response(PayoutSerializer(payouts, many=True).data)


class PayoutDetailView(APIView):
    """
    GET /api/v1/payouts/<payout_id>
    """

    def get(self, request, payout_id):
        payout = get_object_or_404(
            Payout.objects.select_related("bank_account", "merchant"), pk=payout_id
        )
        return Response(PayoutSerializer(payout).data)
