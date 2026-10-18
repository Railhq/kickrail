"""Stripe client factories as dependencies so tests can swap in fakes."""

from collections.abc import Callable

from fastapi import HTTPException

from .services.paypal import PayPal
from .services.stripe_api import MerchantStripe, PlatformStripe

MerchantApiFactory = Callable[[dict], object]


def merchant_api_factory() -> MerchantApiFactory:
    return MerchantStripe.for_merchant


def merchant_key_client() -> Callable[[str], object]:
    """Build a client from a raw restricted key (used while connecting)."""
    return MerchantStripe


def platform_api():
    try:
        return PlatformStripe()
    except RuntimeError as e:
        raise HTTPException(503, str(e))


def paypal_factory() -> Callable[[dict], object]:
    """PayPal client for a merchant's saved credentials."""
    return PayPal.for_merchant


def paypal_key_client() -> Callable[[str, str, str], object]:
    """Build a client from raw credentials (used while connecting)."""
    return PayPal


def billing_api():
    """Kickrail's Stripe account, for charging programs their plan."""
    from .services.billing import Billing

    try:
        return Billing()
    except RuntimeError as e:
        raise HTTPException(503, str(e))


def stripe_oauth():
    """Connect OAuth for one-click "Connect with Stripe"."""
    from .services.stripe_api import StripeOAuth

    try:
        return StripeOAuth()
    except RuntimeError as e:
        raise HTTPException(503, str(e))


def stripe_oauth_optional():
    """The same, or None when it isn't set up (disconnecting still works)."""
    from .services.stripe_api import StripeOAuth

    try:
        return StripeOAuth()
    except RuntimeError:
        return None


def merchant_account_client() -> Callable[[str], object]:
    """Build a client acting as a connected account (used while connecting with OAuth)."""
    return MerchantStripe.for_account


def rewardful_client() -> Callable[[str], object]:
    """Rewardful API client from a pasted API secret (used for one import run)."""
    from .services.rewardful_import import Rewardful

    return Rewardful
