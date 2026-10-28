import { NextResponse, type NextRequest } from "next/server";
import { api, portalSlug, siteUrl } from "@/lib/backend";
import { RAILHQ_FLOW_COOKIE, RAILHQ_TRIED_COOKIE } from "@/lib/session";

/**
 * "Continue with Railhq" and the silent check on the sign-in page (prompt=none): send the
 * browser to Railhq accounts, keeping the kit's `flow` in a short httpOnly cookie for the
 * callback. Dashboard logins only: on a program's portal domain this goes back to /login.
 */
export async function GET(req: NextRequest) {
  const sp = req.nextUrl.searchParams;
  const next = sp.get("next") ?? "/home";
  const prompt = sp.get("prompt") === "none" ? "none" : sp.get("prompt") === "login" ? "login" : "";
  const origin = await siteUrl();
  const back = NextResponse.redirect(new URL(`/login?next=${encodeURIComponent(next)}&error=railhq`, origin), 303);
  if (await portalSlug()) return back;
  let r: { url: string; flow: string };
  try {
    r = await api<{ url: string; flow: string }>("/auth/railhq/start", { auth: false, body: { next, prompt } });
  } catch {
    return back;
  }
  const res = NextResponse.redirect(r.url, 303);
  const secure = process.env.NODE_ENV === "production";
  res.cookies.set(RAILHQ_FLOW_COOKIE, r.flow, { httpOnly: true, sameSite: "lax", secure, path: "/", maxAge: 600 });
  // One silent try per few minutes, so "not signed in to Railhq" doesn't loop.
  if (prompt === "none") res.cookies.set(RAILHQ_TRIED_COOKIE, "1", { httpOnly: true, sameSite: "lax", secure, path: "/", maxAge: 300 });
  return res;
}
