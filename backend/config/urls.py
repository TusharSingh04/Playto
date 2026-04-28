from django.urls import path, include

urlpatterns = [
    path("api/v1/", include("apps.merchants.urls")),
    path("api/v1/", include("apps.payouts.urls")),
    path("api/v1/", include("apps.ledger.urls")),
]
