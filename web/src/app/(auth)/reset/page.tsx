import Link from "next/link";
import { resetPassword } from "@/app/actions";
import { ActionForm, Submit } from "@/components/ActionForm";
import { Field } from "@/components/ui";

export const metadata = { title: "Choose a new password" };

/** Landing for the link in the reset email. */
export default async function Reset({ searchParams }: { searchParams: Promise<{ token?: string }> }) {
  const { token = "" } = await searchParams;
  if (!token) {
    return (
      <>
        <h1 className="font-display text-3xl tracking-tight">Link incomplete</h1>
        <p className="mt-2 text-sm text-muted">Open the full link from your email, or <Link className="link" href="/forgot">ask for a new one</Link>.</p>
      </>
    );
  }
  return (
    <>
      <h1 className="font-display text-3xl tracking-tight">Choose a new password</h1>
      <p className="mt-1 text-sm text-muted">This signs you out everywhere else.</p>
      <ActionForm action={resetPassword} className="mt-6 space-y-4">
        <input type="hidden" name="token" value={token} />
        <Field label="New password" hint="At least 8 characters."><input className="input" name="password" type="password" minLength={8} autoComplete="new-password" required /></Field>
        <Submit className="w-full">Save and sign in</Submit>
      </ActionForm>
    </>
  );
}
