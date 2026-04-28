from django.urls import path
from apps.merchants import views

urlpatterns = [
    path("merchants/", views.MerchantListView.as_view(), name="merchant-list"),
    path("merchants/<uuid:pk>/", views.MerchantDetailView.as_view(), name="merchant-detail"),
    path("merchants/<uuid:merchant_id>/balance/", views.MerchantBalanceView.as_view(), name="merchant-balance"),
]
