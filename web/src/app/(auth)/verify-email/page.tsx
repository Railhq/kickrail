import { redirect } from "next/navigation";
import { logout, resendVerification } from "@/app/actions";
import { ActionForm, Submit } from "@/components/ActionForm";
import { maybe, partnerContext } from "@/lib/backend";
import type { Me, PartnerMe } from "@/lib/me";

export const metadata = { title: "Confirm your email" };

/** Where unverified accounts wait. The link in the email lands on /verify. */
export default async function VerifyEmail({ searchParams }: { searchParams: Promise<{ next?: string }> }) {
  const { next = "/home" } = await searchParams;
  // Whichever login is waiting on its address: the affiliate one on the affiliate side.
  const partner = await partnerContext(next);
  const op = partner ? null : await maybe<Me>("/auth/me");
  const me = op ?? (await maybe<PartnerMe>("/partner/auth/me"));
  if (!me) redirect(`/login?next=${encodeURIComponent(`/verify-email?next=${next}`)}`);
  if (me.user.email_verified) redirect(next.startsWith("/") && !next.startsWith("//") ? next : "/home");
  return (
    <>
      <h1 className="font-display text-3xl tracking-tight">Check your inbox</h1>
      <p className="mt-2 text-sm text-muted">
        We sent a link to <b className="text-fg">{me.user.email}</b>. Open it to confirm the address, and you&apos;re in. It can take a minute, so check spam too.
      </p>
      <ActionForm action={resendVerification} className="mt-6">
        <input type="hidden" name="next" value={next} />
        <input type="hidden" name="side" value={op ? "operator" : "partner"} />
        <Submit variant="secondary" className="w-full">Send the link again</Submit>
      </ActionForm>
      <form action={logout} className="mt-6 text-center text-sm text-muted">
        Wrong address? <button className="link">Sign out</button> and sign up again.
      </form>
    </>
  );
}
