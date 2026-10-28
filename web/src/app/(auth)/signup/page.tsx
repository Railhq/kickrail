import Link from "next/link";
import { signup } from "@/app/actions";
import { ActionForm, Submit } from "@/components/ActionForm";
import { Field } from "@/components/ui";
import { partnerContext } from "@/lib/backend";

export const metadata = { title: "Create account" };

export default async function Signup({ searchParams }: { searchParams: Promise<{ next?: string }> }) {
  const { next = "" } = await searchParams;
  // The affiliate login (a join link, or a program's portal domain).
  const joining = await partnerContext(next);
  return (
    <>
      <h1 className="font-display text-3xl tracking-tight">{joining ? "Create your affiliate account" : "Create your account"}</h1>
      <p className="mt-1 text-sm text-muted">{joining ? "You'll use this one login for every Kickrail program you join." : "Set up an affiliate program for your Stripe product."}</p>
      <ActionForm action={signup} className="mt-6 space-y-4">
        <input type="hidden" name="next" value={next} />
        <Field label="Name" hint={joining ? "Your referral link is based on this, and you can change it later." : undefined}>
          <input className="input" name="name" autoComplete="name" required />
        </Field>
        <Field label="Email"><input className="input" name="email" type="email" autoComplete="email" required /></Field>
        <Field label="Password" hint="At least 8 characters."><input className="input" name="password" type="password" minLength={8} autoComplete="new-password" required /></Field>
        <Submit className="w-full">Create account</Submit>
        <p className="text-center text-xs text-muted">
          By creating an account you agree to the <Link className="link" href="/terms">terms</Link> and <Link className="link" href="/privacy">privacy policy</Link>.
        </p>
      </ActionForm>
      <p className="mt-6 text-center text-sm text-muted">
        Have an account? <Link className="link" href={`/login${next ? `?next=${encodeURIComponent(next)}` : ""}`}>Sign in</Link>
      </p>
    </>
  );
}
