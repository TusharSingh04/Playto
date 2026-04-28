"""
python manage.py process_pending

Inline payout sweep. Use when no Celery worker is running (Render free
tier, local debugging without Redis, etc.).

Production-on-free-tier usage: an external cron pinger (cron-job.org or
similar) hits the protected /api/v1/_internal/cron/sweep/ endpoint every
60 seconds. This management command is the same code path, but invoked
directly so you can run it locally or from a Render Shell session.
"""

import json

from django.core.management.base import BaseCommand

from apps.payouts.processing import sweep_and_process


class Command(BaseCommand):
    help = "Sweep pending + stuck payouts and process them inline."

    def add_arguments(self, parser):
        parser.add_argument(
            "--limit",
            type=int,
            default=50,
            help="Max payouts to handle per sweep (default: 50)",
        )

    def handle(self, *args, **options):
        summary = sweep_and_process(batch_limit=options["limit"])
        self.stdout.write(json.dumps(summary, indent=2, default=str))
