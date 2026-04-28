from django.urls import path
from apps.merchants import auth_views, views

urlpatterns = [
    path("auth/login/", auth_views.LoginView.as_view(), name="auth-login"),
    path("auth/me/", auth_views.WhoAmIView.as_view(), name="auth-me"),
    path("merchants/", views.MerchantListView.as_view(), name="merchant-list"),
    path("merchants/<uuid:pk>/", views.MerchantDetailView.as_view(), name="merchant-detail"),
    path("merchants/<uuid:merchant_id>/balance/", views.MerchantBalanceView.as_view(), name="merchant-balance"),
]
