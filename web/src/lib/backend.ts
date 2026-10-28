import "server-only";
import { headers } from "next/headers";
import { redirect } from "next/navigation";
import { getPartnerSession, getProgram, getSession, isPartnerPath } from "./session";

export const BACKEND_URL = process.env.BACKEND_URL ?? "http://127.0.0.1:8000";

export function internalToken(): string {
  const t = process.env.INTERNAL_TOKEN;
  if (!t) throw new Error("INTERNAL_TOKEN is not set");
  return t;
}

/** Client IP as seen by this server. Behind a load balancer, the LB must set X-Forwarded-For. */
export function clientIp(h: Headers): string {
  return h.get("x-real-ip") ?? h.get("x-forwarded-for")?.split(",")[0].trim() ?? "127.0.0.1";
}

export class ApiError extends Error {
  constructor(public status: number, message: string) {
    super(message);
  }
}

function detail(body: unknown, status: number): string {
  const d = (body as { detail?: unknown })?.detail;
  if (typeof d === "string") return d;
  // FastAPI validation errors: [{loc, msg}]
  if (Array.isArray(d) && d[0]?.msg) return `${d[0].loc?.slice(-1)[0] ?? "input"}: ${d[0].msg}`;
  return `request failed (${status})`;
}

/** Call the backend from server components and server actions, as the signed-in user. */
export async function api<T = unknown>(path: string, init: { method?: string; body?: unknown; auth?: boolean } = {}): Promise<T> {
  const h = await headers();
  const out: Record<string, string> = { "x-internal-token": internalToken(), "x-forwarded-for": clientIp(h) };
  if (init.auth !== false && isPartnerPath(path)) {
    const token = await getPartnerSession();
    if (token) out.authorization = `Bearer ${token}`;
  } else if (init.auth !== false) {
    const token = await getSession();
    if (token) out.authorization = `Bearer ${token}`;
    const program = await getProgram();
    if (program) out["x-kickrail-program"] = program;
  }
  if (init.body !== undefined) out["content-type"] = "application/json";
  const res = await fetch(BACKEND_URL + path, {
    method: init.method ?? (init.body !== undefined ? "POST" : "GET"),
    headers: out,
    body: init.body !== undefined ? JSON.stringify(init.body) : undefined,
    cache: "no-store",
  });
  const text = await res.text();
  const body = text && res.headers.get("content-type")?.includes("json") ? JSON.parse(text) : text;
  if (res.status === 403 && detail(body, 403).startsWith("verify your email")) {
    // Server actions come from a page; send them back to it once the address is confirmed.
    const from = h.get("referer") ? new URL(h.get("referer")!).pathname : "";
    redirect(`/verify-email${from ? `?next=${encodeURIComponent(from)}` : ""}`);
  }
  if (!res.ok) throw new ApiError(res.status, detail(body, res.status));
  return body as T;
}

/** Like api(), but sends signed-out users to /login and returns null on 404. */
export async function authed<T>(path: string, next: string): Promise<T | null> {
  try {
    return await api<T>(path);
  } catch (e) {
    if (e instanceof ApiError && e.status === 401) redirect(`/login?next=${encodeURIComponent(next)}`);
    if (e instanceof ApiError && e.status === 404) return null;
    throw e;
  }
}

/** Like api(), but null when signed out (401) or not found (404), without redirecting. */
export async function maybe<T>(path: string): Promise<T | null> {
  try {
    return await api<T>(path);
  } catch (e) {
    if (e instanceof ApiError && (e.status === 401 || e.status === 404)) return null;
    throw e;
  }
}

/** The program whose portal domain this request came in on (set by middleware), if any. */
export async function portalSlug(): Promise<string | null> {
  return (await headers()).get("x-kickrail-portal-slug");
}

/** Pages for affiliates: a program's portal domain, or a next path on the affiliate side. */
export async function partnerContext(next: string): Promise<boolean> {
  return /^\/(?:a|join|claim)(?:[/?]|$)/.test(next) || Boolean(await portalSlug());
}

/** This site's origin, for links shown to users. */
export async function siteUrl(): Promise<string> {
  const h = await headers();
  const host = h.get("x-forwarded-host") ?? h.get("host") ?? "localhost:3000";
  const proto = h.get("x-forwarded-proto") ?? (host.startsWith("localhost") || host.startsWith("127.") ? "http" : "https");
  return `${proto}://${host}`;
}
