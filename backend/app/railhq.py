"""Railhq accounts client for a Railhq app. One file, vendored as is into each app's
backend (app/railhq.py); depends on httpx and PyJWT[crypto] only. Keep the copies equal:
`make kit` in railhq-accounts copies this file into every app.

    rh = Railhq(issuer, client_id, client_secret, redirect_uri)

    # Sign in with the Railhq page (or silently, prompt="none"):
    url, flow = rh.authorize_url(state_secret, prompt="none")   # keep `flow` in a short cookie
    claims = await rh.finish(code, state, flow, state_secret)   # verified ID token claims

    # Keep the app's own sign-up/sign-in forms: send the details server to server, then
    # send the browser to rh.handoff_url(handoff, ...) so the next app needs no password.
    got = await rh.login(email, password, ip)                    # RailhqError(404|401|429)
    got = await rh.signup(email, password, name, ip)             # RailhqError(409)
    got = await rh.import_user(email, name, bcrypt_hash, email_verified)

    # What accounts.getrailhq.com sends the app:
    rh.verify_logout_token(form["logout_token"])   # back-channel logout: {"sub", "sid"}
    rh.verify_event(body)                          # webhook: {"type", "data"}
    rh.verify_access_token(bearer)                 # MCP gateway calls: {"sub", "email", ...}
"""

import base64
import hashlib
import hmac
import json
import secrets
import time
from urllib.parse import urlencode

import httpx
import jwt

LOGOUT_EVENT = "http://schemas.openid.net/event/backchannel-logout"
FLOW_SECONDS = 600


class RailhqError(Exception):
    def __init__(self, status: int, code: str, message: str, body: dict | None = None):
        super().__init__(message)
        self.status, self.code, self.message, self.body = status, code, message, body or {}


class Railhq:
    def __init__(self, issuer: str, client_id: str, client_secret: str, redirect_uri: str, timeout: float = 15, transport: httpx.AsyncBaseTransport | None = None):
        self.issuer = issuer.rstrip("/")
        self.client_id, self.client_secret, self.redirect_uri = client_id, client_secret, redirect_uri
        self._timeout, self._transport = timeout, transport
        self._jwks: tuple[float, dict] | None = None

    # ---------- HTTP ----------

    def _client(self) -> httpx.AsyncClient:
        return httpx.AsyncClient(base_url=self.issuer, timeout=self._timeout, auth=(self.client_id, self.client_secret), transport=self._transport)

    async def _call(self, method: str, path: str, **kw) -> dict:
        async with self._client() as h:
            try:
                r = await h.request(method, path, **kw)
            except httpx.HTTPError as e:
                raise RailhqError(503, "unreachable", "Railhq accounts didn't answer. Try again in a minute.") from e
        try:
            body = r.json()
        except ValueError:
            body = {}
        if r.status_code >= 400:
            d = body.get("detail") if isinstance(body, dict) else None
            if isinstance(d, dict):
                raise RailhqError(r.status_code, d.get("code", "error"), d.get("message", "error"), d)
            raise RailhqError(r.status_code, body.get("error", "error") if isinstance(body, dict) else "error", str(d or (body.get("error_description") if isinstance(body, dict) else "") or r.text[:200]), body if isinstance(body, dict) else {})
        return body

    # ---------- the authorization code flow ----------

    def _sign(self, secret: str, raw: str) -> str:
        return hmac.new(secret.encode(), raw.encode(), hashlib.sha256).hexdigest()[:32]

    def authorize_url(self, state_secret: str, prompt: str | None = None, login_hint: str | None = None, next_path: str = "/", authorize_path: str = "/authorize") -> tuple[str, str]:
        """(URL to send the browser to, flow value to keep in a short-lived httpOnly cookie)."""
        verifier = secrets.token_urlsafe(48)
        state, nonce = secrets.token_urlsafe(16), secrets.token_urlsafe(16)
        challenge = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).rstrip(b"=").decode()
        q = {"client_id": self.client_id, "redirect_uri": self.redirect_uri, "response_type": "code", "scope": "openid email profile",
             "code_challenge": challenge, "code_challenge_method": "S256", "state": state, "nonce": nonce}
        if prompt:
            q["prompt"] = prompt
        if login_hint:
            q["login_hint"] = login_hint
        raw = json.dumps({"v": verifier, "s": state, "n": nonce, "next": next_path, "t": int(time.time()), "p": prompt or ""}, separators=(",", ":"))
        flow = base64.urlsafe_b64encode(raw.encode()).decode() + "." + self._sign(state_secret, raw)
        return f"{self.issuer}{authorize_path}?{urlencode(q)}", flow

    def authorize_path(self, state_secret: str, **kw) -> tuple[str, str]:
        """Same as authorize_url but the /authorize?... path, for /handoff's `next`."""
        url, flow = self.authorize_url(state_secret, **kw)
        return url[len(self.issuer):], flow

    def read_flow(self, flow: str, state_secret: str) -> dict | None:
        try:
            b, sig = flow.rsplit(".", 1)
            raw = base64.urlsafe_b64decode(b.encode()).decode()
        except (ValueError, UnicodeDecodeError):
            return None
        if not hmac.compare_digest(sig, self._sign(state_secret, raw)):
            return None
        f = json.loads(raw)
        return f if time.time() - f["t"] < FLOW_SECONDS else None

    async def finish(self, code: str, state: str, flow: str, state_secret: str) -> dict:
        """Exchange the code; returns the verified ID token claims plus `next` (the path the
        flow started from) and `access_token`. Raises RailhqError."""
        f = self.read_flow(flow or "", state_secret)
        if not f or not hmac.compare_digest(f["s"], state or ""):
            raise RailhqError(400, "bad_state", "This sign-in took too long or was started in another tab. Try again.")
        tok = await self._call("POST", "/token", data={"grant_type": "authorization_code", "code": code, "code_verifier": f["v"], "redirect_uri": self.redirect_uri})
        claims = await self._verify(tok["id_token"], self.client_id)
        if claims.get("nonce") != f["n"]:
            raise RailhqError(400, "bad_nonce", "This sign-in didn't match. Try again.")
        return claims | {"next": f.get("next") or "/", "access_token": tok.get("access_token")}

    def handoff_url(self, handoff: str, authorize_path: str) -> str:
        return f"{self.issuer}/handoff?" + urlencode({"token": handoff, "next": authorize_path})

    def logout_url(self, post_logout_redirect_uri: str | None = None) -> str:
        q = {"client_id": self.client_id}
        if post_logout_redirect_uri:
            q["post_logout_redirect_uri"] = post_logout_redirect_uri
        return f"{self.issuer}/logout?{urlencode(q)}"

    # ---------- server to server ----------

    async def signup(self, email: str, password: str, name: str = "", ip: str = "") -> dict:
        return await self._call("POST", "/api/signup", json={"email": email, "password": password, "name": name, "ip": ip})

    async def login(self, email: str, password: str, ip: str = "") -> dict:
        return await self._call("POST", "/api/login", json={"email": email, "password": password, "ip": ip})

    async def import_user(self, email: str, name: str, password_hash: str | None, email_verified: bool) -> dict:
        return await self._call("POST", "/api/import", json={"email": email, "name": name, "password_hash": password_hash, "email_verified": email_verified})

    async def forgot(self, email: str) -> dict:
        return await self._call("POST", "/api/forgot", json={"email": email})

    async def user(self, sub: str) -> dict:
        return await self._call("GET", f"/api/users/{sub}")

    async def orgs(self, sub: str) -> list[dict]:
        return (await self._call("GET", f"/api/users/{sub}/orgs"))["orgs"]

    async def resend_verify(self, sub: str) -> dict:
        return await self._call("POST", f"/api/users/{sub}/verify")

    # ---------- tokens accounts sends us ----------

    async def _keys(self) -> dict:
        if not self._jwks or time.time() - self._jwks[0] > 600:
            async with httpx.AsyncClient(base_url=self.issuer, timeout=self._timeout, transport=self._transport) as h:
                r = await h.get("/jwks.json")
                r.raise_for_status()
            self._jwks = (time.time(), {k["kid"]: jwt.PyJWK(k).key for k in r.json()["keys"]})
        return self._jwks[1]

    async def _verify(self, token: str, audience: str, leeway: int = 30) -> dict:
        try:
            kid = jwt.get_unverified_header(token).get("kid")
            ks = await self._keys()
            if kid not in ks:
                self._jwks = None  # a rotated key: fetch once more
                ks = await self._keys()
            return jwt.decode(token, ks[kid], algorithms=["RS256"], audience=audience, issuer=self.issuer, leeway=leeway)
        except (jwt.PyJWTError, KeyError) as e:
            raise RailhqError(401, "bad_token", f"Railhq token not valid: {e}") from e

    async def verify_logout_token(self, token: str) -> dict:
        c = await self._verify(token, self.client_id)
        if LOGOUT_EVENT not in (c.get("events") or {}) or "nonce" in c:
            raise RailhqError(400, "bad_token", "not a logout token")
        return {"sub": c.get("sub"), "sid": c.get("sid")}

    async def verify_event(self, token: str) -> dict:
        c = await self._verify(token, self.client_id)
        return {"id": c.get("jti"), "type": c.get("type"), "data": c.get("data") or {}}

    async def verify_access_token(self, token: str) -> dict:
        """A token the MCP gateway minted for this app, for one person."""
        return await self._verify(token, self.client_id)
