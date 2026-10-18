"""AES-256-GCM for secrets at rest (merchant Stripe keys, webhook secrets)."""

import base64
import hashlib
import os

from cryptography.hazmat.primitives.ciphers.aead import AESGCM

from .config import get_settings


def _key() -> bytes:
    secret = get_settings().app_secret
    if len(secret) < 32:
        raise RuntimeError("APP_SECRET must be 32+ chars")
    return hashlib.sha256(f"enc:{secret}".encode()).digest()


def encrypt(plain: str) -> str:
    nonce = os.urandom(12)
    ct = AESGCM(_key()).encrypt(nonce, plain.encode(), None)
    return base64.urlsafe_b64encode(nonce + ct).decode()


def decrypt(blob: str) -> str:
    raw = base64.urlsafe_b64decode(blob.encode())
    return AESGCM(_key()).decrypt(raw[:12], raw[12:], None).decode()
