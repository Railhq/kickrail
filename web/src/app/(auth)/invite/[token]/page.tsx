import Link from "next/link";
import { acceptInvite } from "@/app/actions";
import { api, ApiError } from "@/lib/backend";
import { getSession } from "@/lib/session";

export const metadata = { title: "Team invite" };

type Invite = { email: string; merchant: { name: string; slug: string }; invited_by: string; has_account: boolean };

export default async function InvitePage({ params, searchParams }: { params: Promise<{ token: string }>; searchParams: Promise<{ error?: string }> }) {
  const [{ token }, { error }] = await Promise.all([params, searchParams]);
  let inv: Invite;
  try {
    inv = await api<Invite>(`/auth/invites/${encodeURIComponent(token)}`, { auth: false });
  } catch (e) {
    if (!(e instanceof ApiError) || e.status !== 404) throw e;
    return (
      <>
        <h1 className="font-display text-3xl tracking-tight">Invite not valid</h1>
        <p className="mt-2 text-sm text-muted">{e.message}. Ask whoever invited you for a new link.</p>
      </>
    );
  }
  const signedIn = !!(await getSession());
  const next = encodeURIComponent(`/invite/${token}`);
  return (
    <>
      <p className="eyebrow">Team invite</p>
      <h1 className="mt-2 font-display text-3xl tracking-tight">Join {inv.merchant.name}</h1>
      <p className="mt-2 text-sm text-muted">
        {inv.invited_by || "A teammate"} invited <b>{inv.email}</b> to help run the {inv.merchant.name} affiliate program on Kickrail.
      </p>
      {error && <p className="mt-4 rounded-lg border border-red-200 bg-red-50 p-3 text-sm text-red-800">{error}</p>}
      {signedIn ? (
        <form action={acceptInvite.bind(null, token)} className="mt-6">
          <button className="btn btn-primary w-full py-2.5">Accept invite</button>
          <p className="mt-3 text-center text-xs text-muted">Signed in as someone else? <Link className="link" href={`/login?next=${next}`}>Switch account</Link></p>
        </form>
      ) : (
        <div className="mt-6 space-y-2">
          <Link className="btn btn-primary w-full py-2.5" href={`/${inv.has_account ? "login" : "signup"}?next=${next}`}>{inv.has_account ? `Sign in as ${inv.email}` : "Create your account"}</Link>
          <p className="text-center text-xs text-muted">
            {inv.has_account ? <>New here? <Link className="link" href={`/signup?next=${next}`}>Create an account</Link></> : <>Have an account? <Link className="link" href={`/login?next=${next}`}>Sign in</Link></>}
          </p>
        </div>
      )}
    </>
  );
}
