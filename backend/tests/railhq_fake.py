"""A stand-in for accounts.getrailhq.com in an app's tests. Vendor it next to railhq.py
(tests/railhq_fake.py). It answers the same endpoints the kit calls, signs with a test
key, and lets a test mint what the real service would send.

    fake = FakeRailhq("seorail")
    rh = Railhq(fake.issuer, "seorail", "secret", "https://app.test/auth/railhq/callback", transport=fake.transport)
    fake.add_user("a@b.com", "password123", verified=True)
    code = fake.code_for(sub, nonce)          # what /authorize would have redirected with
    fake.logout_token(sub, sid); fake.event("user.updated", {"sub": sub}); fake.access_token(sub)
"""

import base64
import json
import secrets
import time
from urllib.parse import parse_qs

import bcrypt
import httpx
import jwt
from cryptography.hazmat.primitives.asymmetric import rsa

LOGOUT_EVENT = "http://schemas.openid.net/event/backchannel-logout"
_KEY = rsa.generate_private_key(public_exponent=65537, key_size=2048)  # one per test run


class FakeRailhq:
    def __init__(self, client_id: str, issuer: str = "https://accounts.railhq.test"):
        self.client_id, self.issuer = client_id, issuer
        self.users: dict[str, dict] = {}
        self.orgs: dict[str, list] = {}
        self.codes: dict[str, dict] = {}
        self.calls: list[tuple[str, str, dict]] = []
        self.transport = httpx.MockTransport(self._handle)

    # ---------- test helpers ----------

    def add_user(self, email: str, password: str | None = "password123", name: str = "", verified: bool = True, password_hash: str | None = None) -> dict:
        sub = "usr_" + secrets.token_hex(6)
        h = password_hash or (bcrypt.hashpw(password.encode(), bcrypt.gensalt(4)).decode() if password else None)
        u = {"sub": sub, "email": email.strip().lower(), "name": name, "email_verified": verified, "pass": False, "_hash": h}
        self.users[sub] = u
        return self.pub(u)

    def by_email(self, email: str) -> dict | None:
        return next((u for u in self.users.values() if u["email"] == email.strip().lower()), None)

    @staticmethod
    def pub(u: dict) -> dict:
        return {k: u[k] for k in ("sub", "email", "email_verified", "name", "pass")}

    def sign(self, claims: dict, ttl: int = 600, typ: str = "JWT") -> str:
        now = int(time.time())
        return jwt.encode({"iss": self.issuer, "iat": now, "exp": now + ttl, **claims}, _KEY, algorithm="RS256", headers={"kid": "test", "typ": typ})

    def code_for(self, sub: str, nonce: str) -> str:
        code = secrets.token_urlsafe(16)
        self.codes[code] = {"sub": sub, "nonce": nonce}
        return code

    def logout_token(self, sub: str, sid: str) -> str:
        return self.sign({"aud": self.client_id, "jti": secrets.token_hex(8), "sub": sub, "sid": sid, "events": {LOGOUT_EVENT: {}}}, typ="logout+jwt")

    def event(self, kind: str, data: dict) -> str:
        return self.sign({"aud": self.client_id, "jti": "evt_" + secrets.token_hex(6), "type": kind, "data": data}, typ="railhq-event+jwt")

    def access_token(self, sub: str, aud: str | None = None) -> str:
        """What the MCP gateway sends an app's MCP endpoint."""
        u = self.users[sub]
        return self.sign({"aud": aud or self.client_id, "sub": sub, "client_id": "railhq-gateway", "email": u["email"], "scope": "mcp", "act": {"sub": "railhq-gateway"}, "jti": secrets.token_hex(8)}, 300, "at+jwt")

    # ---------- the endpoints ----------

    def _who(self, u: dict) -> dict:
        return {"user": self.pub(u), "apps": [self.client_id], "handoff": "hof_" + secrets.token_urlsafe(8)}

    def _handle(self, req: httpx.Request) -> httpx.Response:
        path = req.url.path
        body = json.loads(req.content) if req.headers.get("content-type", "").startswith("application/json") and req.content else {}
        self.calls.append((req.method, path, body))
        if path == "/jwks.json":
            pub = _KEY.public_key().public_numbers()
            b64 = lambda n: base64.urlsafe_b64encode(n.to_bytes((n.bit_length() + 7) // 8, "big")).rstrip(b"=").decode()
            return httpx.Response(200, json={"keys": [{"kty": "RSA", "kid": "test", "alg": "RS256", "use": "sig", "n": b64(pub.n), "e": b64(pub.e)}]})
        if path == "/token":
            f = {k: v[0] for k, v in parse_qs(req.content.decode()).items()}
            c = self.codes.pop(f.get("code", ""), None)
            if not c:
                return httpx.Response(400, json={"error": "invalid_grant"})
            u = self.users[c["sub"]]
            idt = self.sign(self.pub(u) | {"aud": self.client_id, "nonce": c["nonce"], "sid": "sid_" + secrets.token_hex(6), "auth_time": int(time.time())})
            return httpx.Response(200, json={"id_token": idt, "access_token": self.access_token(u["sub"]), "token_type": "Bearer", "expires_in": 3600})
        if path == "/api/signup":
            if self.by_email(body["email"]):
                return httpx.Response(409, json={"detail": {"code": "exists", "message": "a Railhq account with this email already exists", "apps": ["Seorail"]}})
            u = self.users[self.add_user(body["email"], body["password"], body.get("name", ""), verified=False)["sub"]]
            return httpx.Response(201, json=self._who(u))
        if path == "/api/login":
            u = self.by_email(body["email"])
            if not u:
                return httpx.Response(404, json={"detail": {"code": "no_account", "message": "no Railhq account with this email"}})
            if not u["_hash"] or not bcrypt.checkpw(body["password"].encode(), u["_hash"].encode()):
                return httpx.Response(401, json={"detail": {"code": "wrong_password", "message": "wrong password"}})
            return httpx.Response(200, json=self._who(u))
        if path == "/api/import":
            u = self.by_email(body["email"])
            if u:
                return httpx.Response(409, json={"detail": {"code": "exists", "message": "exists", "apps": [], "email_verified": u["email_verified"]}})
            u = self.users[self.add_user(body["email"], None, body.get("name", ""), body.get("email_verified", False), body.get("password_hash"))["sub"]]
            return httpx.Response(200, json=self._who(u))
        if path == "/api/forgot":
            return httpx.Response(200, json={"ok": True})
        if path.startswith("/api/users/"):
            parts = path.split("/")
            u = self.users.get(parts[3])
            if not u:
                return httpx.Response(404, json={"detail": "no such user"})
            if len(parts) == 5 and parts[4] == "orgs":
                return httpx.Response(200, json={"orgs": self.orgs.get(u["sub"], [])})
            if len(parts) == 5 and parts[4] == "verify":
                return httpx.Response(200, json={"ok": True})
            return httpx.Response(200, json=self.pub(u))
        return httpx.Response(404, json={"detail": f"fake has no {path}"})
