import Link from "next/link";
import { forgotPassword } from "@/app/actions";
import { ActionForm, Submit } from "@/components/ActionForm";
import { Field } from "@/components/ui";

export const metadata = { title: "Reset your password" };

/** `next` keeps the affiliate side on the affiliate login (see actions.forgotPassword). */
export default async function Forgot({ searchParams }: { searchParams: Promise<{ next?: string }> }) {
  const { next = "" } = await searchParams;
  return (
    <>
      <h1 className="font-display text-3xl tracking-tight">Reset your password</h1>
      <p className="mt-1 text-sm text-muted">We&apos;ll email you a link to choose a new one.</p>
      <ActionForm action={forgotPassword} className="mt-6 space-y-4">
        <input type="hidden" name="next" value={next} />
        <Field label="Email"><input className="input" name="email" type="email" autoComplete="email" required /></Field>
        <Submit className="w-full">Send reset link</Submit>
      </ActionForm>
      <p className="mt-6 text-center text-sm text-muted">Remembered it? <Link className="link" href={`/login${next ? `?next=${encodeURIComponent(next)}` : ""}`}>Sign in</Link></p>
    </>
  );
}
