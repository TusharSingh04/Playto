"""
Inline payout processing — used when no Celery worker is available
(e.g. Render free tier). Same correctness guarantees as the Celery tasks:

- SELECT FOR UPDATE row locks prevent two concurrent runs from acting on
  the same payout.
- State machine transitions go through Payout.transition_to() so backward
  transitions are rejected at the DB.
- settle_payout_success / settle_payout_failure run inside transaction.atomic(),
  so the ledger entry and state change land together or not at all.

The Celery tasks in tasks.py and these functions deliberately share NO
implementation — they wrap the same service-layer primitives. Either path
can be enabled in isolation (controlled by settings.PAYOUT_USE_CELERY).
"""

import logging
import random
import time
from datetime import timedelta

from django.conf import settings
from django.db import transaction
from django.utils import timezone

from apps.payouts.exceptions import PayoutTransitionError
from apps.payouts.models import Payout, PayoutState
from apps.payouts.service import settle_payout_failure, settle_payout_success

logger = logging.getLogger(__name__)

OUTCOME_SUCCESS_PROBABILITY = 0.70
OUTCOME_FAILURE_PROBABILITY = 0.20
# Remaining 10% → "stuck" (simulated): we don't settle, and the next sweep
# will pick the row up after PAYOUT_STUCK_THRESHOLD_SECONDS.

# Note: the cron-style sweep doesn't apply Celery's retry-with-countdown.
# Stuck rows just get re-processed on the next sweep tick. Attempts are
# still bumped each cycle, so PAYOUT_MAX_ATTEMPTS still bounds retries.


def _simulate_bank_call() -> str:
    """Returns 'success', 'failure', or 'stuck'."""
    time.sleep(random.uniform(0.05, 0.3))
    r = random.random()
    if r < OUTCOME_SUCCESS_PROBABILITY:
        return "success"
    if r < OUTCOME_SUCCESS_PROBABILITY + OUTCOME_FAILURE_PROBABILITY:
        return "failure"
    return "stuck"


def process_one_payout(payout_id: str) -> dict:
    """
    Process a single payout end-to-end, inline.

    Returns a dict describing the outcome — useful for the cron endpoint
    to surface in its JSON response.

    Idempotent: safe to call multiple times for the same payout. Already-
    terminal payouts are no-ops; PROCESSING payouts re-run the simulation
    (the sweep treats this as a retry).
    """
    try:
        with transaction.atomic():
            payout = (
                Payout.objects.select_for_update(skip_locked=True)
                .select_related("merchant", "bank_account")
                .get(pk=payout_id)
            )

            if payout.state in (PayoutState.COMPLETED, PayoutState.FAILED):
                return {"status": "already_terminal", "state": payout.state, "id": str(payout_id)}

            if payout.state == PayoutState.PENDING:
                try:
                    payout.transition_to(PayoutState.PROCESSING)
                    Payout.objects.filter(pk=payout.pk).update(attempts=payout.attempts + 1)
                    payout.attempts += 1
                except PayoutTransitionError as exc:
                    logger.warning("Transition error for %s: %s", payout_id, exc)
                    return {"status": "transition_conflict", "id": str(payout_id)}
    except Payout.DoesNotExist:
        # skip_locked => row is held by a concurrent sweep. Skip.
        return {"status": "skipped_locked_or_missing", "id": str(payout_id)}

    # Bank call happens OUTSIDE the row lock so we don't hold a SELECT FOR
    # UPDATE for hundreds of ms. The state machine + guarded UPDATE in
    # settle_* protects us if a concurrent sweep also picks this row.
    outcome = _simulate_bank_call()
    logger.info("Payout %s outcome=%s", payout_id, outcome)

    if outcome == "success":
        try:
            settle_payout_success(payout)
        except PayoutTransitionError:
            return {"status": "concurrent_settled", "id": str(payout_id)}
        return {"status": "completed", "id": str(payout_id)}

    if outcome == "failure":
        try:
            settle_payout_failure(payout, reason="Bank API returned failure.")
        except PayoutTransitionError:
            return {"status": "concurrent_settled", "id": str(payout_id)}
        return {"status": "failed", "id": str(payout_id)}

    return {"status": "stuck", "id": str(payout_id)}


def sweep_and_process(batch_limit: int = 50) -> dict:
    """
    Single sweep: process pending + retry stuck. Designed to be called
    every minute by an external cron pinger.

    Returns a dict summary safe to JSON-serialise.
    """
    now = timezone.now()
    stuck_threshold = settings.PAYOUT_STUCK_THRESHOLD_SECONDS
    max_attempts = settings.PAYOUT_MAX_ATTEMPTS
    summary = {
        "processed_pending": [],
        "retried_stuck": [],
        "exhausted_failed": [],
    }

    # ── 1. Process pending ────────────────────────────────────────────────
    pending_ids = list(
        Payout.objects.filter(state=PayoutState.PENDING)
        .order_by("created_at")
        .values_list("id", flat=True)[:batch_limit]
    )
    for pid in pending_ids:
        result = process_one_payout(str(pid))
        summary["processed_pending"].append(result)

    # ── 2. Retry / fail stuck ─────────────────────────────────────────────
    stuck_cutoff = now - timedelta(seconds=stuck_threshold)
    with transaction.atomic():
        stuck = list(
            Payout.objects.filter(
                state=PayoutState.PROCESSING,
                processing_started_at__lt=stuck_cutoff,
            ).select_for_update(skip_locked=True)[:batch_limit]
        )
        for payout in stuck:
            if payout.attempts >= max_attempts:
                try:
                    settle_payout_failure(
                        payout, reason=f"Exceeded max attempts ({max_attempts})."
                    )
                    summary["exhausted_failed"].append(str(payout.id))
                except PayoutTransitionError as exc:
                    logger.error("Exhaust failed for %s: %s", payout.id, exc)
            else:
                # Re-tick: refresh processing_started_at + bump attempts.
                # process_one_payout will re-run the simulation when state
                # is PROCESSING. The state machine forbids backward moves,
                # so we never reset to PENDING.
                Payout.objects.filter(pk=payout.pk, state=PayoutState.PROCESSING).update(
                    processing_started_at=now,
                    attempts=payout.attempts + 1,
                )
                summary["retried_stuck"].append(str(payout.id))

    # Process the freshly-bumped stuck rows in this same sweep so they
    # actually move forward instead of waiting another minute.
    for pid in summary["retried_stuck"]:
        process_one_payout(pid)

    return summary
