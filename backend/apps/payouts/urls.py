from django.urls import path
from apps.payouts import views

urlpatterns = [
    path("payouts/", views.PayoutCreateView.as_view(), name="payout-create"),
    path("payouts/<uuid:payout_id>/", views.PayoutDetailView.as_view(), name="payout-detail"),
    path("merchants/<uuid:merchant_id>/payouts/", views.PayoutListView.as_view(), name="payout-list"),
]
