/**
 * Custom portal domains. A merchant points partners.example.com at portals.kickrail.com
 * with a CNAME. That host is a small Caddy proxy (deploy/portal-proxy) that gets the
 * certificate and forwards to this app as kickrail.com, passing the real hostname and
 * client IP in x-kickrail-* headers signed with PORTAL_PROXY_TOKEN. On that host "/" is
 * the merchant's join page, /join/<campaign> a public campaign's, and everything else (/a, /login, /claim) works as usual.
 * Kickrail's own hosts skip the lookup.
 */
import { NextRequest, NextResponse } from "next/server";

const BACKEND_URL = process.env.BACKEND_URL ?? "http://127.0.0.1:8000";
const OWN_HOSTS = new Set((process.env.APP_HOSTS ?? "localhost,127.0.0.1").split(",").map((h) => h.trim().toLowerCase()));
const PROXY_TOKEN = process.env.PORTAL_PROXY_TOKEN ?? "";
const PROXY_HEADERS = ["x-kickrail-proxy-token", "x-kickrail-portal-host", "x-kickrail-client-ip"];
const TTL_MS = 60_000;
const cache = new Map<string, { slug: string | null; at: number }>();

async function slugFor(host: string): Promise<string | null> {
  const hit = cache.get(host);
  if (hit && Date.now() - hit.at < TTL_MS) return hit.slug;
  let slug: string | null = null;
  try {
    const res = await fetch(`${BACKEND_URL}/domains/${encodeURIComponent(host)}`, { headers: { "x-internal-token": process.env.INTERNAL_TOKEN ?? "" }, cache: "no-store" });
    if (res.ok) slug = ((await res.json()) as { slug: string }).slug;
  } catch {
    return null; // backend down: don't cache, fall through to the normal site
  }
  if (cache.size > 1000) cache.clear();
  cache.set(host, { slug, at: Date.now() });
  return slug;
}

function sameSecret(a: string, b: string): boolean {
  if (!a || a.length !== b.length) return false;
  let diff = 0;
  for (let i = 0; i < a.length; i++) diff |= a.charCodeAt(i) ^ b.charCodeAt(i);
  return diff === 0;
}

export async function middleware(req: NextRequest) {
  const fromProxy = PROXY_TOKEN !== "" && sameSecret(req.headers.get("x-kickrail-proxy-token") ?? "", PROXY_TOKEN);
  const headers = new Headers(req.headers);
  PROXY_HEADERS.forEach((h) => headers.delete(h));
  let host = (req.headers.get("x-forwarded-host") ?? req.headers.get("host") ?? "").split(":")[0].toLowerCase();
  if (fromProxy) {
    // Pages, server actions (which check Origin against this) and siteUrl() see the real hostname.
    const portal = (req.headers.get("x-kickrail-portal-host") ?? "").toLowerCase();
    host = portal.split(":")[0];
    headers.set("x-forwarded-host", portal);
    headers.set("x-forwarded-proto", "https");
    const ip = req.headers.get("x-kickrail-client-ip");
    if (ip) {
      headers.set("x-real-ip", ip);
      headers.set("x-forwarded-for", ip);
    }
  }
  const next = () => NextResponse.next({ request: { headers } });
  const { pathname } = req.nextUrl;
  if (!host || OWN_HOSTS.has(host) || pathname.startsWith("/api/")) return next();
  const slug = await slugFor(host);
  if (!slug) return next();
  // Kickrail's blog is proxied in next.config; it doesn't belong on a merchant's domain.
  if (pathname === "/blog" || pathname.startsWith("/blog/")) return new NextResponse("Not found", { status: 404 });
  // The merchant dashboard stays on Kickrail's own domain.
  if (pathname === "/" || pathname === "/join" || pathname.startsWith("/dashboard") || pathname.startsWith("/onboarding")) {
    return NextResponse.rewrite(new URL(`/join/${slug}`, req.url), { request: { headers } });
  }
  // partners.example.com/join/creators is that campaign's own join page.
  const campaign = pathname.match(/^\/join\/([^/]+)\/?$/)?.[1];
  if (campaign && campaign !== slug) {
    return NextResponse.rewrite(new URL(`/join/${slug}/${campaign}`, req.url), { request: { headers } });
  }
  return next();
}

export const config = {
  // Pages and the API proxy, not Next internals or static files.
  matcher: ["/((?!_next/|favicon.ico|.*\\.[a-z0-9]+$).*)"],
};
