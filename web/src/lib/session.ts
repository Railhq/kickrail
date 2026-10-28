import "server-only";
import { cookies } from "next/headers";

/** The dashboard login (operators). Sessions from before the operator/affiliate split are
 * here too, and the backend accepts those on both sides. */
export const SESSION_COOKIE = "kr_session";
/** The affiliate login, separate from the dashboard's (backend routers/partner_auth.py). */
export const PARTNER_COOKIE = "kr_partner";
/** Railhq sign-in in progress (the kit's `flow`), and the guard on the silent check. */
export const RAILHQ_FLOW_COOKIE = "railhq_flow";
export const RAILHQ_TRIED_COOKIE = "railhq_tried";
/** Which of the user's programs the dashboard shows. The backend checks membership. */
export const PROGRAM_COOKIE = "kr_program";

export async function getSession(): Promise<string | undefined> {
  return (await cookies()).get(SESSION_COOKIE)?.value;
}

/** Affiliate side: its own cookie, else a session from before the split. */
export async function getPartnerSession(): Promise<string | undefined> {
  const jar = await cookies();
  return jar.get(PARTNER_COOKIE)?.value ?? jar.get(SESSION_COOKIE)?.value;
}

export const sessionCookie = { httpOnly: true, sameSite: "lax", secure: process.env.NODE_ENV === "production", path: "/", maxAge: 60 * 60 * 24 * 30 } as const;

export async function setSession(token: string) {
  (await cookies()).set(SESSION_COOKIE, token, sessionCookie);
}

export async function setPartnerSession(token: string) {
  (await cookies()).set(PARTNER_COOKIE, token, sessionCookie);
}

/** Signing out ends both logins, as it did when they were one. */
export async function clearSession() {
  const jar = await cookies();
  jar.delete(SESSION_COOKIE);
  jar.delete(PARTNER_COOKIE);
  jar.delete(PROGRAM_COOKIE);
}

/** Backend paths that act as the affiliate, not the dashboard user. */
export function isPartnerPath(path: string): boolean {
  return /^\/(?:portal(?:[/?]|$)|payout-account|tax-info|partner\/|programs\/[^/]+\/join(?:[/?]|$))/.test(path);
}

export async function getProgram(): Promise<string | undefined> {
  return (await cookies()).get(PROGRAM_COOKIE)?.value;
}

export async function setProgram(id: string) {
  (await cookies()).set(PROGRAM_COOKIE, id, { httpOnly: true, sameSite: "lax", secure: process.env.NODE_ENV === "production", path: "/", maxAge: 60 * 60 * 24 * 365 });
}
