import Link from "next/link";
import { api, ApiError } from "@/lib/backend";
import { getSession } from "@/lib/session";

export const metadata = { title: "Email confirmed" };

/** Landing for the link in the confirmation email. */
export default async function Verify({ searchParams }: { searchParams: Promise<{ token?: string }> }) {
  const { token = "" } = await searchParams;
  let result: { email: string; next: string | null } | null = null;
  let error = "Open the full link from your email.";
  if (token) {
    try {
      result = await api<{ email: string; next: string | null }>("/auth/verify", { auth: false, body: { token } });
    } catch (e) {
      if (!(e instanceof ApiError)) throw e;
      error = e.message;
    }
  }
  if (!result) {
    return (
      <>
        <h1 className="font-display text-3xl tracking-tight">Link didn&apos;t work</h1>
        <p className="mt-2 text-sm text-muted">{error.charAt(0).toUpperCase() + error.slice(1)}.</p>
        <Link className="btn btn-secondary mt-6 w-full" href="/verify-email">Get a new link</Link>
      </>
    );
  }
  const next = result.next ?? "/home";
  // Opened in another browser than the one they signed up in: they still need to sign in there.
  const signedIn = Boolean(await getSession());
  return (
    <>
      <h1 className="font-display text-3xl tracking-tight">Email confirmed</h1>
      <p className="mt-2 text-sm text-muted"><b className="text-fg">{result.email}</b> is confirmed. Thanks.</p>
      <Link className="btn btn-primary mt-6 w-full" href={signedIn ? next : `/login?next=${encodeURIComponent(next)}`}>{signedIn ? "Continue" : "Sign in to continue"}</Link>
    </>
  );
}
