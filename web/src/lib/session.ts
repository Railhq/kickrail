import "server-only";
import { cookies } from "next/headers";

export const SESSION_COOKIE = "kr_session";
/** Which of the user's programs the dashboard shows. The backend checks membership. */
export const PROGRAM_COOKIE = "kr_program";

export async function getSession(): Promise<string | undefined> {
  return (await cookies()).get(SESSION_COOKIE)?.value;
}

export async function setSession(token: string) {
  (await cookies()).set(SESSION_COOKIE, token, {
    httpOnly: true,
    sameSite: "lax",
    secure: process.env.NODE_ENV === "production",
    path: "/",
    maxAge: 60 * 60 * 24 * 30,
  });
}

export async function clearSession() {
  const jar = await cookies();
  jar.delete(SESSION_COOKIE);
  jar.delete(PROGRAM_COOKIE);
}

export async function getProgram(): Promise<string | undefined> {
  return (await cookies()).get(PROGRAM_COOKIE)?.value;
}

export async function setProgram(id: string) {
  (await cookies()).set(PROGRAM_COOKIE, id, { httpOnly: true, sameSite: "lax", secure: process.env.NODE_ENV === "production", path: "/", maxAge: 60 * 60 * 24 * 365 });
}
