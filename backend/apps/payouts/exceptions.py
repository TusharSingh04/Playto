from rest_framework.views import exception_handler
from rest_framework.response import Response
from rest_framework import status


class InsufficientFundsError(Exception):
    pass


class PayoutTransitionError(Exception):
    pass


class IdempotencyConflictError(Exception):
    """Raised when same idempotency key is in-flight from another request."""
    pass


def custom_exception_handler(exc, context):
    response = exception_handler(exc, context)

    if isinstance(exc, InsufficientFundsError):
        return Response(
            {"error": "insufficient_funds", "detail": str(exc)},
            status=status.HTTP_422_UNPROCESSABLE_ENTITY,
        )

    if isinstance(exc, PayoutTransitionError):
        return Response(
            {"error": "invalid_transition", "detail": str(exc)},
            status=status.HTTP_409_CONFLICT,
        )

    if isinstance(exc, IdempotencyConflictError):
        return Response(
            {"error": "idempotency_conflict", "detail": str(exc)},
            status=status.HTTP_409_CONFLICT,
        )

    return response
