import uuid
import logging

from django.conf import settings
from django.shortcuts import get_object_or_404
from django.utils.decorators import method_decorator
from django_ratelimit.decorators import ratelimit
from rest_framework import status
from rest_framework.exceptions import PermissionDenied, Throttled
from rest_framework.response import Response
from rest_framework.throttling import ScopedRateThrottle
from rest_framework.views import APIView

from apps.merchants.permissions import require_owned_merchant
from apps.payouts.models import Payout
from apps.payouts.serializers import CreatePayoutSerializer, PayoutSerializer
from apps.payouts.service import create_payout

logger = logging.getLogger(__name__)


def _resolve_merchant(request):
    """Always derive merchant from the authenticated user. Never trust the body."""
    merchant = getattr(request.user, "merchant", None)
    if merchant is None:
        raise PermissionDenied("This user is not linked to a merchant account.")
    return merchant


def _user_or_ip(group, request):
    """Rate-limit key: per-user when authed, per-IP otherwise.

    Keying on user.id is critical — IP-only would let one merchant's heavy
    traffic starve another behind the same NAT.
    """
    if request.user.is_authenticated:
        return f"user:{request.user.pk}"
    return request.META.get("REMOTE_ADDR", "anon")


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

    # Defense-in-depth: DRF throttle is per-process (in-memory) by default.
    # django-ratelimit uses the shared cache (Redis in prod) so the limit is
    # enforced across every gunicorn worker and every machine in the cluster.
    # 5/min per user matches the prod throttle in production.py.
    @method_decorator(
        ratelimit(key=_user_or_ip, rate="5/m", method="POST", block=False)
    )
    def post(self, request):
        if getattr(request, "limited", False):
            # block=False above means we read the flag and respond ourselves
            # so we can return a JSON 429 (not the html ratelimited page).
            raise Throttled(detail="Too many payout requests. Slow down.")

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

            # Dispatch for async processing.
            #   - If a Celery worker is configured (PAYOUT_USE_CELERY=True),
            #     enqueue the task and return immediately.
            #   - Otherwise (free-tier deployments), the payout sits in
            #     PENDING until the external cron pinger hits the sweep
            #     endpoint and drives it forward.
            if settings.PAYOUT_USE_CELERY:
                # Imported lazily so codepaths without Celery installed/running
                # don't import it just to skip the call.
                from apps.payouts.tasks import process_payout
                process_payout.delay(str(payout.id))
                logger.info("Enqueued process_payout for %s (celery)", payout.id)
            else:
                logger.info(
                    "Payout %s left PENDING for cron-driven processing", payout.id
                )

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
