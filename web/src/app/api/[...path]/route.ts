/**
 * Public edge of the backend. Everything under /api/* is forwarded to FastAPI:
 * the tracking script and beacons, Stripe webhooks (raw body, so signatures verify),
 * the merchant server API (sk_kr_ bearer keys), and same-origin browser calls
 * (which get the session cookie turned into a bearer token here).
 */
import { NextRequest } from "next/server";
import { BACKEND_URL, clientIp, internalToken } from "@/lib/backend";
import { PROGRAM_COOKIE, SESSION_COOKIE } from "@/lib/session";

export const dynamic = "force-dynamic";

const DROP_REQUEST = new Set(["host", "connection", "content-length", "cookie", "x-internal-token", "x-forwarded-for", "x-real-ip"]);
const DROP_RESPONSE = new Set(["connection", "transfer-encoding", "content-encoding", "content-length", "keep-alive"]);

async function proxy(req: NextRequest, ctx: { params: Promise<{ path: string[] }> }) {
  const { path } = await ctx.params;
  const target = `${BACKEND_URL}/${path.map(encodeURIComponent).join("/")}${req.nextUrl.search}`;

  const headers = new Headers();
  req.headers.forEach((v, k) => {
    if (!DROP_REQUEST.has(k)) headers.set(k, v);
  });
  headers.set("x-internal-token", internalToken());
  headers.set("x-forwarded-for", clientIp(req.headers));
  // Only same-origin browser requests may act as the signed-in user.
  const session = req.cookies.get(SESSION_COOKIE)?.value;
  const site = req.headers.get("sec-fetch-site");
  if (session && !headers.has("authorization") && (site === null || site === "same-origin")) {
    headers.set("authorization", `Bearer ${session}`);
    // Downloads and polls from the dashboard act on the program picked in the switcher.
    const program = req.cookies.get(PROGRAM_COOKIE)?.value;
    if (program && !headers.has("x-kickrail-program")) headers.set("x-kickrail-program", program);
  }

  const hasBody = !["GET", "HEAD"].includes(req.method);
  const res = await fetch(target, {
    method: req.method,
    headers,
    body: hasBody ? await req.arrayBuffer() : undefined,
    redirect: "manual",
    cache: "no-store",
  });

  const out = new Headers();
  res.headers.forEach((v, k) => {
    if (!DROP_RESPONSE.has(k)) out.set(k, v);
  });
  return new Response(res.status === 204 || req.method === "HEAD" ? null : res.body, { status: res.status, headers: out });
}

export { proxy as GET, proxy as POST, proxy as PUT, proxy as PATCH, proxy as DELETE, proxy as OPTIONS, proxy as HEAD };
