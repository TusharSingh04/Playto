from django.urls import path
from apps.ledger import views

urlpatterns = [
    path("merchants/<uuid:merchant_id>/ledger/", views.MerchantLedgerView.as_view(), name="ledger-history"),
]
