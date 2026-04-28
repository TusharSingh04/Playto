"""
Authorization helpers — ensure the requesting user owns the merchant they
are operating on. The DRF permission classes here are the single chokepoint
that prevents merchant-A from reading or transacting against merchant-B.
"""

from rest_framework.exceptions import NotFound, PermissionDenied


def require_owned_merchant(request, merchant_id):
    """
    Raise PermissionDenied if request.user does not own merchant_id.

    Returns the Merchant instance on success.

    NOTE: We deliberately raise NotFound (not Forbidden) for non-owned
    merchants so an attacker can't enumerate which merchant_ids exist.
    """
    merchant = getattr(request.user, "merchant", None)
    if merchant is None:
        raise PermissionDenied("This user is not linked to a merchant account.")
    if str(merchant.id) != str(merchant_id):
        raise NotFound("Merchant not found.")
    return merchant
