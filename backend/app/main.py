import asyncio
import contextlib
import hmac
import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from .config import get_settings
from .db import close_db, get_db
from .routers import assets, auth, billing, developers, mcp, merchant, partner_auth, portal, public, railhq, server_api, team, webhooks
from .services.billing import check_limits
from .services.outbox import run_dispatcher
from .services.payouts import announce_due, poll_paypal
from .services.paypal import PayPal
from .services.stripe_api import MerchantStripe
from .services.stripe_events import catch_up_payment_intents
from .services.stripe_sync import sync_customers

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")


async def _periodic(db) -> None:
    await poll_paypal(db, PayPal.for_merchant)
    await check_limits(db)
    await announce_due(db)
    await catch_up_payment_intents(db, MerchantStripe.for_merchant)


async def _each(db) -> None:
    await sync_customers(db, MerchantStripe.for_merchant)


@asynccontextmanager
async def lifespan(_: FastAPI):
    db = await get_db()
    task = asyncio.create_task(run_dispatcher(db, extra=_periodic, each=_each)) if get_settings().dispatcher else None
    yield
    if task:
        task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await task
    await close_db()


app = FastAPI(title="Kickrail API", lifespan=lifespan)


@app.middleware("http")
async def internal_only(request: Request, call_next):
    """Only the web proxy talks to this service. It is not exposed publicly."""
    if request.url.path != "/health":
        sent = request.headers.get("x-internal-token", "")
        if not hmac.compare_digest(sent, get_settings().internal_token):
            return JSONResponse({"detail": "forbidden"}, status_code=403)
    return await call_next(request)


@app.get("/health")
async def health():
    return {"ok": True}


for r in (assets.router, auth.router, billing.router, developers.router, mcp.router, merchant.router, partner_auth.router, portal.router, public.router, railhq.router, server_api.router, team.router, webhooks.router):
    app.include_router(r)
