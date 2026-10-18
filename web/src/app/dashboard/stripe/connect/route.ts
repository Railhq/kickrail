import { NextResponse, type NextRequest } from "next/server";
import { api, ApiError, siteUrl } from "@/lib/backend";
import { getSession, setProgram } from "@/lib/session";

/**
 * The Stripe connect link an agent hands the user (the MCP connect_stripe tool):
 * sign in, switch to that program, and go straight to Stripe's approval page.
 */
export async function GET(req: NextRequest) {
  const program = req.nextUrl.searchParams.get("program") ?? "";
  const here = `/dashboard/stripe/connect?program=${encodeURIComponent(program)}`;
  const origin = await siteUrl();
  const to = (path: string) => NextResponse.redirect(new URL(path, origin));
  if (!(await getSession())) return to(`/login?next=${encodeURIComponent(here)}`);
  if (!/^mer_[A-Za-z0-9]+$/.test(program)) return to("/dashboard/settings#stripe");
  await setProgram(program);
  try {
    // The backend falls back to another program when this account isn't on the one asked for.
    const m = await api<{ id: string }>("/merchant");
    if (m.id !== program) return to("/home");
    if ((m as { stripe?: unknown }).stripe) return to("/dashboard/settings#stripe");
    const { url } = await api<{ url: string }>("/merchant/stripe/oauth");
    return NextResponse.redirect(url);
  } catch (e) {
    if (e instanceof ApiError && e.status === 401) return to(`/login?next=${encodeURIComponent(here)}`);
    return to("/dashboard/settings#stripe");
  }
}
