"""A program's Kickrail plan: what it's on, usage against the cap, checkout and the Stripe billing portal."""

import logging
from datetime import UTC, datetime, timedelta
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from .. import plans
from ..config import get_settings
from ..deps import billing_api
from ..security import current_merchant, current_user, db_dep
from ..services import billing, pass_coverage

log = logging.getLogger(__name__)
router = APIRouter(prefix="/merchant/billing", tags=["billing"])


def catalog() -> list[dict]:
    return [{"id": pid, **{k: v for k, v in plans.PLANS[pid].items()}} for pid in plans.ORDER]


@router.get("")
async def overview(m=Depends(current_merchant), user=Depends(current_user), db=Depends(db_dep)):
    from .merchant import plan_summary

    return {
        "plan": plan_summary(m),
        "plans": catalog(),
        "usage": await billing.usage(db, m),
        "teammates": len(m.get("member_ids") or []),
        "campaigns": await db.campaigns.count_documents({"merchant_id": m["_id"], "archived_at": {"$exists": False}}),
        "domains": len(m.get("portal_domains") or []),
        "enabled": bool(get_settings().billing_key),
        "can_manage": user["_id"] == m.get("owner_id"),
        # For an owner with a Railhq Pass: how many programs it covers and whether this is one.
        "railhq_pass": {"workspaces": n, "covered": bool(m.get("railhq_pass"))} if (n := pass_coverage.allowance(user)) and user["_id"] == m.get("owner_id") else None,
    }


class CheckoutIn(BaseModel):
    plan: Literal["starter", "growth", "scale"]
    interval: Literal["month", "year"] = "month"


def _owner(m: dict, user: dict) -> None:
    if user["_id"] != m.get("owner_id"):
        raise HTTPException(403, "only the program owner can change the plan")


@router.post("/checkout")
async def checkout(body: CheckoutIn, m=Depends(current_merchant), user=Depends(current_user), db=Depends(db_dep), api=Depends(billing_api)):
    """A Stripe Checkout link for a new subscription, or an in-place plan change for an existing one."""
    _owner(m, user)
    if m.get("comped"):
        raise HTTPException(409, "this program is on Kickrail for free")
    p = m.get("plan") or {}
    price = await api.price_id(body.plan, body.interval)
    if plans.current(m)["subscribed"]:
        sub = await api.change_price(p["stripe_subscription"], price)
        outcome = await billing.apply_subscription(db, sub)
        log.info("plan change %s -> %s", m["_id"], outcome)
        return {"changed": True}
    now = datetime.now(UTC)
    trial = plans.current(m, now)
    # Still in the no-card trial: the card is charged when it ends (Stripe needs 2+ days of notice).
    trial_end = int(trial["trial_ends_at"].timestamp()) if trial["status"] == "trialing" and trial["trial_ends_at"] and trial["trial_ends_at"] > now + timedelta(days=2, minutes=5) else None
    base = get_settings().public_url
    url = await api.checkout(
        merchant_id=m["_id"], customer=p.get("stripe_customer"), email=user["email"], price=price, trial_end=trial_end,
        success_url=f"{base}/dashboard/billing?done=1", cancel_url=f"{base}/dashboard/billing",
    )
    return {"url": url}


@router.post("/portal")
async def portal(m=Depends(current_merchant), user=Depends(current_user), api=Depends(billing_api)):
    _owner(m, user)
    customer = (m.get("plan") or {}).get("stripe_customer")
    if not customer:
        raise HTTPException(400, "there's no billing account yet; pick a plan first")
    return {"url": await api.portal(customer, f"{get_settings().public_url}/dashboard/billing")}
