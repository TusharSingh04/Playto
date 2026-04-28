from django.urls import path
from apps.payouts import cron_views, views

urlpatterns = [
    path("payouts/", views.PayoutCreateView.as_view(), name="payout-create"),
    path("payouts/<uuid:payout_id>/", views.PayoutDetailView.as_view(), name="payout-detail"),
    path("merchants/<uuid:merchant_id>/payouts/", views.PayoutListView.as_view(), name="payout-list"),
    # Internal — protected by X-Cron-Secret header. Called by an external
    # cron pinger when no Celery worker is provisioned.
    path("_internal/cron/sweep/", cron_views.CronSweepView.as_view(), name="cron-sweep"),
    # Authenticated alternative — called by the React dashboard's polling
    # loop. Same processing logic, no shared secret, just login required.
    path("payouts/_sweep/", cron_views.AuthSweepView.as_view(), name="payout-sweep"),
]
