"""A program's own terms of service, written in the dashboard's editor and hosted by
Kickrail. The editor sends HTML, so it is cleaned to a short allowlist before it is
stored; the join page and portal render what is stored as is."""

import nh3

TAGS = {"p", "br", "strong", "b", "em", "i", "u", "ul", "ol", "li", "a", "h2", "h3", "blockquote"}
MAX_HTML = 100_000


def clean(html: str) -> str:
    out = nh3.clean(
        html,
        tags=TAGS,
        attributes={"a": {"href"}},
        url_schemes={"http", "https", "mailto"},
        link_rel="noopener noreferrer nofollow",
    ).strip()
    # An editor cleared down to an empty paragraph is no terms at all.
    return "" if out in ("<p></p>", "<p><br></p>") else out


def public(m: dict) -> dict | None:
    t = m.get("terms")
    return {"title": t["title"], "html": t["html"], "updated_at": t["updated_at"]} if t else None
