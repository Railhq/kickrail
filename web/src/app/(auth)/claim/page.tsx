import Link from "next/link";
import { claimAccount } from "@/app/actions";
import { ActionForm, Submit } from "@/components/ActionForm";
import { Field } from "@/components/ui";

export const metadata = { title: "Set your password" };

/** Landing for the link in the welcome email of an affiliate a program added for you. */
export default async function Claim({ searchParams }: { searchParams: Promise<{ token?: string }> }) {
  const { token = "" } = await searchParams;
  if (!token) {
    return (
      <>
        <h1 className="font-display text-3xl tracking-tight">Link incomplete</h1>
        <p className="mt-2 text-sm text-muted">Open the full link from your welcome email, or <Link className="link" href="/login">sign in</Link>.</p>
      </>
    );
  }
  return (
    <>
      <h1 className="font-display text-3xl tracking-tight">Set your password</h1>
      <p className="mt-1 text-sm text-muted">A program added you as an affiliate. Choose a password to see your links, referrals and earnings.</p>
      <ActionForm action={claimAccount} className="mt-6 space-y-4">
        <input type="hidden" name="token" value={token} />
        <Field label="Your name" hint="Optional. Leave empty to keep the name the program used."><input className="input" name="name" autoComplete="name" maxLength={100} /></Field>
        <Field label="Password" hint="At least 8 characters."><input className="input" name="password" type="password" minLength={8} autoComplete="new-password" required /></Field>
        <Submit className="w-full">Save and continue</Submit>
      </ActionForm>
      <p className="mt-6 text-center text-sm text-muted">Already set one? <Link className="link" href="/login?next=/a">Sign in</Link></p>
    </>
  );
}
