import { NextResponse, type NextRequest } from "next/server";
import { api, siteUrl } from "@/lib/backend";
import { RAILHQ_FLOW_COOKIE, SESSION_COOKIE, sessionCookie } from "@/lib/session";

function safeNext(n: unknown): string {
  return typeof n === "string" && n.startsWith("/") && !n.startsWith("//") ? n : "/home";
}

/** The path the sign-in started from, read from the flow cookie (the backend checks its signature). */
function flowNext(flow: string): string {
  try {
    return safeNext(JSON.parse(Buffer.from(flow.split(".")[0], "base64url").toString()).next);
  } catch {
    return "/home";
  }
}

/** Where Railhq accounts sends the browser back with a code (or an error). */
export async function GET(req: NextRequest) {
  const sp = req.nextUrl.searchParams;
  const flow = req.cookies.get(RAILHQ_FLOW_COOKIE)?.value ?? "";
  const origin = await siteUrl();
  const go = (path: string) => {
    const res = NextResponse.redirect(new URL(path, origin), 303);
    res.cookies.delete(RAILHQ_FLOW_COOKIE);
    return res;
  };
  const next = flowNext(flow);
  const error = sp.get("error");
  // Not signed in to Railhq (the silent check): the normal sign-in page.
  if (error === "login_required") return go(`/login?next=${encodeURIComponent(next)}`);
  if (error || !sp.get("code") || !flow) return go(`/login?next=${encodeURIComponent(next)}&error=railhq`);
  let r: { token: string; next: string };
  try {
    r = await api<{ token: string; next: string }>("/auth/railhq/callback", { auth: false, body: { code: sp.get("code"), state: sp.get("state") ?? "", flow } });
  } catch {
    return go(`/login?next=${encodeURIComponent(next)}&error=railhq`);
  }
  const res = go(safeNext(r.next));
  res.cookies.set(SESSION_COOKIE, r.token, sessionCookie);
  return res;
}
