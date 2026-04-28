import uuid
import logging

from django.shortcuts import get_object_or_404
from rest_framework import status
from rest_framework.exceptions import PermissionDenied
from rest_framework.response import Response
from rest_framework.throttling import ScopedRateThrottle
from rest_framework.views import APIView

from apps.merchants.permissions import require_owned_merchant
from apps.payouts.models import Payout
from apps.payouts.serializers import CreatePayoutSerializer, PayoutSerializer
from apps.payouts.service import create_payout
from apps.payouts.tasks import process_payout

logger = logging.getLogger(__name__)


def _resolve_merchant(request):
    """Always derive merchant from the authenticated user. Never trust the body."""
    merchant = getattr(request.user, "merchant", None)
    if merchant is None:
        raise PermissionDenied("This user is not linked to a merchant account.")
    return merchant


class PayoutCreateView(APIView):
    """
    POST /api/v1/payouts

    Required header: Idempotency-Key (UUID)
    Auth: Token (Authorization: Token <key>)

    The merchant is resolved from request.user — clients cannot spoof
    merchant_id by sending it in the body.

    Creates a payout atomically with a ledger hold.
    Enqueues async Celery task for processing.
    """

    throttle_classes = [ScopedRateThrottle]
    throttle_scope = "payout_create"

    def post(self, request):
        merchant = _resolve_merchant(request)

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
        serializer = CreatePayoutSerializer(data=request.data)
        if not serializer.is_valid():
            return Response(
                {"error": "validation_error", "detail": serializer.errors},
                status=status.HTTP_400_BAD_REQUEST,
            )

        # ── Core payout creation (service handles all locking + atomicity) ────
        payout, created = create_payout(
            merchant_id=merchant.id,
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
                    merchant_id=merchant.id, key=raw_key
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
    Authorization: only the merchant's own user may list its payouts.
    """

    def get(self, request, merchant_id):
        merchant = require_owned_merchant(request, merchant_id)
        payouts = (
            Payout.objects.filter(merchant=merchant)
            .select_related("bank_account")
            .order_by("-created_at")[:100]
        )
        return Response(PayoutSerializer(payouts, many=True).data)


class PayoutDetailView(APIView):
    """
    GET /api/v1/payouts/<payout_id>
    Authorization: only the owning merchant's user may read.
    Returns 404 (not 403) on cross-tenant access to avoid id enumeration.
    """

    def get(self, request, payout_id):
        payout = get_object_or_404(
            Payout.objects.select_related("bank_account", "merchant"), pk=payout_id
        )
        require_owned_merchant(request, payout.merchant_id)
        return Response(PayoutSerializer(payout).data)
