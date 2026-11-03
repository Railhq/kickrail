import "server-only";

const ACCOUNTS = process.env.RAILHQ_ACCOUNTS_URL || "https://accounts.getrailhq.com";

/** Whether Railhq accounts offers "Continue with Google" (its /api/providers). The button
 *  goes through /auth/railhq/start?idp=google, which Railhq sends straight on to Google. */
export async function railhqGoogle(): Promise<boolean> {
  try {
    const r = await fetch(`${ACCOUNTS}/api/providers`, { next: { revalidate: 300 } });
    return r.ok && (await r.json()).google === true;
  } catch {
    return false;
  }
}

/** The Railhq /authorize URL, told to skip its own page and go to Google when asked. */
export function withIdp(url: string, params: URLSearchParams): string {
  if (params.get("idp") !== "google" || params.get("prompt") === "none") return url;
  return `${url}${url.includes("?") ? "&" : "?"}idp=google`;
}
