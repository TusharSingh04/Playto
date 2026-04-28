"""
Internal cron endpoint — called every ~60s by an external pinger
(e.g. cron-job.org) when no Celery worker is available. Protected by
a shared secret in the X-Cron-Secret header so it's not publicly
triggerable.

DO NOT expose this URL outside of the cron pinger. Keep CRON_SECRET
out of source control. If the secret leaks, the worst an attacker can
do is force the API to run a sweep — they can't create payouts or read
merchant data through it. Still: rotate the secret if exposed.
"""

import hmac
import logging

from django.conf import settings
from rest_framework import status
from rest_framework.permissions import AllowAny
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.payouts.processing import sweep_and_process

logger = logging.getLogger(__name__)


class CronSweepView(APIView):
    """
    POST /api/v1/_internal/cron/sweep/
    Header: X-Cron-Secret: <CRON_SECRET>
    """

    permission_classes = [AllowAny]
    authentication_classes: list = []
    throttle_classes: list = []

    def post(self, request):
        provided = request.headers.get("X-Cron-Secret", "")
        expected = getattr(settings, "CRON_SECRET", "") or ""

        # Constant-time compare to defend against timing oracle attacks.
        if not expected:
            logger.error("CRON_SECRET is unset — refusing to run sweep.")
            return Response(
                {"error": "cron_unconfigured"},
                status=status.HTTP_503_SERVICE_UNAVAILABLE,
            )
        if not hmac.compare_digest(provided.encode(), expected.encode()):
            logger.warning("Cron sweep called with bad secret from %s", request.META.get("REMOTE_ADDR"))
            return Response(
                {"error": "unauthorized"},
                status=status.HTTP_401_UNAUTHORIZED,
            )

        summary = sweep_and_process()
        logger.info(
            "Cron sweep done: pending=%d retried=%d exhausted=%d",
            len(summary["processed_pending"]),
            len(summary["retried_stuck"]),
            len(summary["exhausted_failed"]),
        )
        return Response(summary)
