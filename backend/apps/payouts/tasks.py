"""
Celery tasks for payout processing.

Design decisions:
- select_for_update(skip_locked=True) ensures multiple workers don't
  race to process the same payout.
- Exponential backoff: retry delay doubles each attempt.
- Max 3 attempts; on exhaustion the payout is failed and funds released.
- Stuck detection: payouts in 'processing' for > PAYOUT_STUCK_THRESHOLD_SECONDS
  are re-queued (they may have crashed mid-flight).
"""

import logging
import random
import time

from celery import shared_task
from django.conf import settings
from django.db import transaction
from django.utils import timezone

from apps.payouts.exceptions import PayoutTransitionError
from apps.payouts.models import Payout, PayoutState
from apps.payouts.service import settle_payout_failure, settle_payout_success

logger = logging.getLogger(__name__)

# Outcome probabilities (must sum to 1.0)
OUTCOME_SUCCESS_PROBABILITY = 0.70
OUTCOME_FAILURE_PROBABILITY = 0.20
# 0.10 → stuck (simulated by not calling either settle function)

RETRY_BASE_DELAY_SECONDS = 5  # Doubled each attempt: 5, 10, 20


@shared_task(bind=True, max_retries=0, name="payouts.process_payout")
def process_payout(self, payout_id: str) -> dict:
    """
    Process a single payout.

    This task is idempotent: if the payout is already in a terminal state
    (completed/failed), it exits cleanly. The select_for_update(skip_locked=True)
    inside poll_and_dispatch prevents duplicate processing.
    """
    logger.info("Processing payout id=%s attempt=%s", payout_id, self.request.retries)

    try:
        with transaction.atomic():
            payout = (
                Payout.objects.select_for_update(skip_locked=True)
                .select_related("merchant", "bank_account")
                .get(pk=payout_id)
            )
    except Payout.DoesNotExist:
        logger.error("Payout %s not found", payout_id)
        return {"status": "not_found", "payout_id": payout_id}

    # Already in terminal state — idempotent no-op
    if payout.state in (PayoutState.COMPLETED, PayoutState.FAILED):
        logger.info("Payout %s already terminal (%s), skipping", payout_id, payout.state)
        return {"status": "already_terminal", "state": payout.state}

    # Transition pending → processing
    if payout.state == PayoutState.PENDING:
        try:
            payout.transition_to(PayoutState.PROCESSING)
            Payout.objects.filter(pk=payout.pk).update(attempts=payout.attempts + 1)
            payout.attempts += 1
        except PayoutTransitionError as exc:
            logger.warning("Transition error for %s: %s", payout_id, exc)
            return {"status": "transition_conflict"}

    # Simulate the external bank API call
    outcome = _simulate_bank_call()
    logger.info("Payout %s outcome=%s", payout_id, outcome)

    if outcome == "success":
        settle_payout_success(payout)
        return {"status": "completed", "payout_id": payout_id}

    elif outcome == "failure":
        settle_payout_failure(payout, reason="Bank API returned failure.")
        return {"status": "failed", "payout_id": payout_id}

    else:  # "stuck"
        # We do NOT settle here. The stuck-detection poll will pick it up
        # after PAYOUT_STUCK_THRESHOLD_SECONDS and re-dispatch.
        logger.warning("Payout %s is stuck (simulated)", payout_id)
        return {"status": "stuck", "payout_id": payout_id}


@shared_task(name="payouts.poll_and_dispatch")
def poll_and_dispatch() -> dict:
    """
    Periodic task (run every ~10s via Celery beat).

    1. Enqueue all PENDING payouts for processing.
    2. Re-enqueue PROCESSING payouts that have been stuck > threshold.
       If exhausted max attempts → fail them and release funds.

    Uses skip_locked so concurrent poll_and_dispatch invocations (if Celery
    beat fires while a prior run is still executing) don't double-enqueue.
    """
    now = timezone.now()
    stuck_threshold = settings.PAYOUT_STUCK_THRESHOLD_SECONDS
    max_attempts = settings.PAYOUT_MAX_ATTEMPTS
    dispatched = []
    stuck_retried = []
    exhausted_failed = []

    # ── Dispatch pending payouts ──────────────────────────────────────────────
    pending_ids = list(
        Payout.objects.filter(state=PayoutState.PENDING)
        .values_list("id", flat=True)
        [:50]  # batch cap to avoid overwhelming the queue
    )
    for payout_id in pending_ids:
        process_payout.delay(str(payout_id))
        dispatched.append(str(payout_id))

    # ── Re-enqueue or fail stuck processing payouts ───────────────────────────
    from datetime import timedelta
    stuck_cutoff = now - timedelta(seconds=stuck_threshold)

    stuck_payouts = list(
        Payout.objects.filter(
            state=PayoutState.PROCESSING,
            processing_started_at__lt=stuck_cutoff,
        ).select_for_update(skip_locked=True)[:20]
    )

    for payout in stuck_payouts:
        if payout.attempts >= max_attempts:
            # Reset to pending so process_payout can transition it, then fail it
            # Actually: fail directly here since we have the payout object
            try:
                # Force state back to processing (it already is) then fail
                settle_payout_failure(payout, reason=f"Exceeded max attempts ({max_attempts}).")
                exhausted_failed.append(str(payout.id))
                logger.warning("Payout %s exhausted retries, marked failed", payout.id)
            except PayoutTransitionError as exc:
                logger.error("Failed to exhaust payout %s: %s", payout.id, exc)
        else:
            # Reset to pending for re-dispatch with exponential backoff
            delay = RETRY_BASE_DELAY_SECONDS * (2 ** payout.attempts)
            with transaction.atomic():
                Payout.objects.filter(pk=payout.pk, state=PayoutState.PROCESSING).update(
                    state=PayoutState.PENDING,
                    processing_started_at=None,
                )
            process_payout.apply_async(args=[str(payout.id)], countdown=delay)
            stuck_retried.append(str(payout.id))
            logger.info(
                "Payout %s re-queued after stuck detection (delay=%ds, attempt=%d)",
                payout.id,
                delay,
                payout.attempts,
            )

    return {
        "dispatched": dispatched,
        "stuck_retried": stuck_retried,
        "exhausted_failed": exhausted_failed,
    }


def _simulate_bank_call() -> str:
    """
    Simulate bank API latency and outcome.
    Returns 'success', 'failure', or 'stuck'.
    """
    time.sleep(random.uniform(0.05, 0.3))  # simulate network round-trip

    r = random.random()
    if r < OUTCOME_SUCCESS_PROBABILITY:
        return "success"
    elif r < OUTCOME_SUCCESS_PROBABILITY + OUTCOME_FAILURE_PROBABILITY:
        return "failure"
    else:
        return "stuck"
