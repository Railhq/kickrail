"""Print cloud-init user data for the portal proxy droplet.

    PORTAL_PROXY_TOKEN=... python3 render.py > user-data.yaml
"""
import os
import sys
from pathlib import Path

here = Path(__file__).parent
token = os.environ.get("PORTAL_PROXY_TOKEN", "")
if len(token) < 32:
    sys.exit("set PORTAL_PROXY_TOKEN (32+ characters)")
caddyfile = "\n".join(f"      {line}" if line else "" for line in (here / "Caddyfile").read_text().splitlines())
out = (here / "cloud-init.yaml").read_text().replace("__CADDYFILE__", caddyfile).replace("__PORTAL_PROXY_TOKEN__", token)
sys.stdout.write(out)
