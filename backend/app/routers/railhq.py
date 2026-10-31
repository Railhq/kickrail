"""Signing in with Railhq accounts (accounts.getrailhq.com), when settings.railhq_enabled.

Only for the people who run programs (users). Affiliates have their own login on each
program's portal (routers/partner_auth.py) and never touch Railhq.

Kickrail keeps its own users, programs and sessions; a person is linked to their Railhq
account by users.railhq_id. The sign-in and sign-up forms still post to routers/auth.py,
which checks the password with Railhq server to server, then sends the browser through
Railhq's /handoff so the next Railhq tool needs no password. People who signed up before
the switch are moved over the first time they sign in with their old password.

    GET  /auth/railhq            whether the web app offers Railhq
    POST /auth/railhq/start      a URL for "Continue with Railhq" (or a silent check)
    POST /auth/railhq/callback   the code Railhq sent the browser back with
    POST /railhq/backchannel     Railhq signing someone out everywhere
    POST /railhq/events          account changes and the Railhq Pass
    GET  /railhq/pass-workspaces which owned programs the Pass covers
    PUT  /railhq/pass-workspaces pick them (owner only, at most the Pass's count)

The web app keeps the `flow` from start in an httpOnly cookie and hands it to callback.
Railhq reaches the last two through the web app's /api proxy."""

import logging
from datetime import UTC, datetime, timedelta
from functools import lru_cache
from urllib.parse import parse_qs

import httpx
from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field

from ..config import get_settings
from ..ids import new_id
from ..railhq import Railhq, RailhqError
from ..security import SESSION_DAYS, current_user, db_dep, issue_token, public_user
from ..services import pass_coverage
from ..services.pass_coverage import set_pass, workspaces_from

log = logging.getLogger("kickrail.railhq")
router = APIRouter(tags=["railhq"])

_transport: httpx.AsyncBaseTransport | None = None  # tests swap in railhq_fake


def set_transport(t: httpx.AsyncBaseTransport | None) -> None:
    global _transport
    _transport = t
    client.cache_clear()


@lru_cache
def client() -> Railhq:
    s = get_settings()
    return Railhq(s.railhq_issuer, s.railhq_client_id, s.railhq_client_secret, f"{s.public_url}/auth/railhq/callback", transport=_transport)


def enabled() -> bool:
    return get_settings().railhq_enabled


def _on() -> None:
    if not enabled():
        raise HTTPException(404, "Railhq sign-in isn't switched on")


def safe_next(n: str | None) -> str:
    return n if n and n.startswith("/") and not n.startswith("//") else "/home"


def handoff(handoff_token: str, next_path: str | None) -> dict:
    """Where the browser goes after a password sign-in, and the flow cookie to set first."""
    rh = client()
    path, flow = rh.authorize_path(get_settings().app_secret, next_path=safe_next(next_path))
    return {"railhq_handoff": rh.handoff_url(handoff_token, path), "railhq_flow": flow}


def _later() -> datetime:
    return datetime.now(UTC).replace(microsecond=0) + timedelta(seconds=1)


async def link(db, who: dict, proven: bool = False) -> dict:
    """The Kickrail operator for a Railhq person (ID token claims or the API's user): the
    linked one, else the one with the same email, else a new one (who then sets up a
    program in onboarding, as after a Kickrail sign-up).

    Joining an existing account by email needs the email confirmed at Railhq, or `proven`
    (they just typed that account's Kickrail password): a Railhq account can be made for any
    address, and must not open someone else's programs."""
    from .auth import drop_legacy_partner

    sub, email, verified = who["sub"], who["email"].lower(), bool(who.get("email_verified"))
    user = await db.users.find_one({"railhq_id": sub})
    if not user:
        await drop_legacy_partner(db, email)
        user = await db.users.find_one({"email": email})
        if user and user.get("railhq_id"):
            raise HTTPException(409, "this email's Kickrail account is linked to another Railhq account")
        if user and not (verified or proven):
            raise HTTPException(403, "confirm your email first: Railhq sent you a link. Then sign in again")
    if not user:
        name = (who.get("name") or email.split("@")[0]).strip()[:100]
        user = {"_id": new_id("usr"), "email": email, "name": name, "railhq_id": sub, "railhq_pass": bool(who.get("pass")), "railhq_pass_workspaces": workspaces_from(who), "ip_hashes": [], "email_verified": verified, "created_at": datetime.now(UTC)}
        await db.users.insert_one(user)
        return user
    s: dict = {"railhq_id": sub}
    if verified:
        s["email_verified"] = True
    if user["email"] != email and verified and not await db.users.find_one({"email": email, "_id": {"$ne": user["_id"]}}):
        s["email"] = email  # changed (and confirmed) at Railhq since we last saw them
    await db.users.update_one({"_id": user["_id"]}, {"$set": s})
    if bool(user.get("railhq_pass")) != bool(who.get("pass")) or user.get("railhq_pass_workspaces") != workspaces_from(who):
        await set_pass(db, user["_id"], bool(who.get("pass")), workspaces_from(who))
    return await db.users.find_one({"_id": user["_id"]})


class StartIn(BaseModel):
    next: str = Field(default="/home", max_length=500)
    prompt: str = Field(default="", pattern="^(|none|login)$")
    email: str = Field(default="", max_length=320)


@router.get("/auth/railhq")
async def railhq_on():
    """For the web app: whether to offer Railhq on the operator sign-in."""
    if not enabled():
        return {"railhq": False, "issuer": None}
    return {"railhq": True, "issuer": get_settings().railhq_issuer}


@router.post("/auth/railhq/start")
async def start(body: StartIn):
    _on()
    url, flow = client().authorize_url(get_settings().app_secret, prompt=body.prompt or None, login_hint=body.email or None, next_path=safe_next(body.next))
    return {"url": url, "flow": flow}


class CallbackIn(BaseModel):
    code: str = Field(min_length=1, max_length=2000)
    state: str = Field(min_length=1, max_length=200)
    flow: str = Field(min_length=1, max_length=4000)


@router.post("/auth/railhq/callback")
async def callback(body: CallbackIn, db=Depends(db_dep)):
    _on()
    try:
        claims = await client().finish(body.code, body.state, body.flow, get_settings().app_secret)
    except RailhqError as e:
        raise HTTPException(400 if e.status < 500 else 503, e.message)
    user = await link(db, claims)
    return {"token": issue_token(user, railhq_sid=claims.get("sid")), "user": public_user(user), "next": safe_next(claims.get("next"))}


@router.post("/railhq/backchannel")
async def backchannel(request: Request, db=Depends(db_dep)):
    _on()
    form = parse_qs((await request.body()).decode(errors="replace"))
    try:
        t = await client().verify_logout_token((form.get("logout_token") or [""])[0])
    except RailhqError as e:
        raise HTTPException(400, e.message)
    if t.get("sid"):
        await db.railhq_signouts.update_one({"_id": t["sid"]}, {"$set": {"expires_at": datetime.now(UTC) + timedelta(days=SESSION_DAYS + 1)}}, upsert=True)
    elif t.get("sub"):
        await db.users.update_one({"railhq_id": t["sub"]}, {"$set": {"signed_out_at": _later()}})
    return {"ok": True}


@router.post("/railhq/events")
async def events(request: Request, db=Depends(db_dep)):
    _on()
    try:
        e = await client().verify_event((await request.body()).decode())
    except (RailhqError, UnicodeDecodeError) as ex:
        raise HTTPException(400, getattr(ex, "message", "not a Railhq event"))
    sub = e["data"].get("sub")
    user = sub and await db.users.find_one({"railhq_id": sub})
    if not user:
        return {"ok": True}  # someone who never ran a program here
    if e["type"] == "user.updated":
        try:
            fresh = await client().user(sub)  # the account itself, not wrapped
        except RailhqError as ex:
            if ex.status == 404:
                return {"ok": True}
            raise HTTPException(503, "couldn't read the account; send it again")
        await link(db, fresh)
        await db.users.update_one({"_id": user["_id"]}, {"$set": {"name": fresh.get("name") or user.get("name", "")}})
    elif e["type"] == "user.deleted":
        # Programs stay; the person signs in with a new Railhq account to reach them.
        await db.users.update_one({"_id": user["_id"]}, {"$unset": {"railhq_id": ""}, "$set": {"signed_out_at": _later()}})
        await set_pass(db, user["_id"], False)
    elif e["type"] == "pass.updated":
        await set_pass(db, user["_id"], bool(e["data"].get("pass")), workspaces_from(e["data"]))
    # orgs.updated: Kickrail programs aren't linked to Railhq organizations.
    return {"ok": True}


def _coverage(user: dict, programs: list[dict], covered: list[str]) -> dict:
    n = pass_coverage.allowance(user)
    return {
        "pass": n > 0,
        "workspaces": n,
        "used": len(covered),
        "programs": [{"id": m["_id"], "name": m.get("name", ""), "created_at": m.get("created_at"), "covered": m["_id"] in covered} for m in programs],
    }


@router.get("/railhq/pass-workspaces")
async def pass_workspaces(user=Depends(current_user), db=Depends(db_dep)):
    """The programs this person owns and which ones their Railhq Pass covers."""
    programs = await pass_coverage.owned(db, user["_id"])
    return _coverage(user, programs, pass_coverage.choose(user, programs))


class PassPickIn(BaseModel):
    workspace_ids: list[str] = Field(max_length=50)


@router.put("/railhq/pass-workspaces")
async def pick_pass_workspaces(body: PassPickIn, user=Depends(current_user), db=Depends(db_dep)):
    """Choose which owned programs the Pass covers, in order. Slots left over go to the
    oldest owned programs."""
    n = pass_coverage.allowance(user)
    if not n:
        raise HTTPException(400, "you don't have a Railhq Pass")
    picks = list(dict.fromkeys(body.workspace_ids))
    if len(picks) > n:
        raise HTTPException(400, f"your Pass covers {n} workspace{'s' if n != 1 else ''}. Upgrade at accounts.getrailhq.com/billing to cover more")
    programs = await pass_coverage.owned(db, user["_id"])
    mine = {m["_id"] for m in programs}
    if any(p not in mine for p in picks):
        raise HTTPException(403, "only a program's owner can put it on their Pass")
    await db.users.update_one({"_id": user["_id"]}, {"$set": {"railhq_pass_pick": picks}})
    user = await db.users.find_one({"_id": user["_id"]})
    covered = await pass_coverage.refresh(db, user["_id"])
    return _coverage(user, await pass_coverage.owned(db, user["_id"]), covered)
