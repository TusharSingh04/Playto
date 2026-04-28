"""
Authentication views — token issue + identity check.

A merchant logs in with username + password and receives an opaque token.
That token is then sent as `Authorization: Token <key>` on every API call.
The merchant identity is derived server-side from the token's User —
clients can NEVER spoof merchant_id by sending it in a body.
"""

from django.contrib.auth import authenticate
from rest_framework import status
from rest_framework.authtoken.models import Token
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView


class LoginView(APIView):
    """
    POST /api/v1/auth/login/
    Body: { "username": "...", "password": "..." }
    Returns: { "token": "...", "merchant_id": "<uuid>" }
    """

    permission_classes = [AllowAny]
    authentication_classes: list = []  # don't try to authenticate the request

    def post(self, request):
        username = (request.data.get("username") or "").strip()
        password = request.data.get("password") or ""
        if not username or not password:
            return Response(
                {"error": "missing_credentials", "detail": "username and password are required."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        user = authenticate(request, username=username, password=password)
        if user is None:
            return Response(
                {"error": "invalid_credentials", "detail": "Login failed."},
                status=status.HTTP_401_UNAUTHORIZED,
            )

        merchant = getattr(user, "merchant", None)
        if merchant is None:
            return Response(
                {"error": "no_merchant", "detail": "This user is not linked to a merchant account."},
                status=status.HTTP_403_FORBIDDEN,
            )

        token, _ = Token.objects.get_or_create(user=user)
        return Response(
            {"token": token.key, "merchant_id": str(merchant.id), "name": merchant.name},
            status=status.HTTP_200_OK,
        )


class WhoAmIView(APIView):
    """
    GET /api/v1/auth/me/
    Returns the merchant tied to the auth token. Useful for the frontend on boot.
    """

    permission_classes = [IsAuthenticated]

    def get(self, request):
        merchant = getattr(request.user, "merchant", None)
        if merchant is None:
            return Response(
                {"error": "no_merchant"}, status=status.HTTP_403_FORBIDDEN
            )
        return Response(
            {"merchant_id": str(merchant.id), "name": merchant.name, "email": merchant.email}
        )
