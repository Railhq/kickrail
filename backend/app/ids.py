import hashlib
import re
import secrets
import string
import unicodedata

from .config import get_settings

_ALPHABET = string.digits + string.ascii_letters


def random_id(length: int = 20) -> str:
    return "".join(secrets.choice(_ALPHABET) for _ in range(length))


def new_id(prefix: str) -> str:
    return f"{prefix}_{random_id()}"


def sha256(s: str) -> str:
    return hashlib.sha256(s.encode()).hexdigest()


def hash_ip(ip: str) -> str:
    """IPs are only ever stored hashed, salted with the app secret."""
    return sha256(f"{get_settings().app_secret}:{ip}")[:32]


def slugify(s: str) -> str:
    s = unicodedata.normalize("NFKD", s.lower()).encode("ascii", "ignore").decode()
    return re.sub(r"[^a-z0-9]+", "-", s).strip("-")[:32]
