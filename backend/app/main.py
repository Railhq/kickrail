import asyncio
import contextlib
import hmac
import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from .config import get_settings
from .db import close_db, get_db
from .routers import auth, billing, developers, mcp, merchant, portal, public, server_api, team, webhooks
from .services.billing import check_limits
from .services.outbox import run_dispatcher
from .services.payouts import announce_due, poll_paypal
from .services.paypal import PayPal

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")


async def _periodic(db) -> None:
    await poll_paypal(db, PayPal.for_merchant)
    await check_limits(db)
    await announce_due(db)


@asynccontextmanager
async def lifespan(_: FastAPI):
    db = await get_db()
    task = asyncio.create_task(run_dispatcher(db, extra=_periodic)) if get_settings().dispatcher else None
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


for r in (auth.router, billing.router, developers.router, mcp.router, merchant.router, portal.router, public.router, server_api.router, team.router, webhooks.router):
    app.include_router(r)
