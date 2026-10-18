import Link from "next/link";
import { login } from "@/app/actions";
import { ActionForm, Submit } from "@/components/ActionForm";
import { Field } from "@/components/ui";

export const metadata = { title: "Sign in" };

export default async function Login({ searchParams }: { searchParams: Promise<{ next?: string }> }) {
  const { next = "" } = await searchParams;
  return (
    <>
      <h1 className="font-display text-3xl tracking-tight">Sign in</h1>
      <p className="mt-1 text-sm text-muted">One account for your program and every program you promote.</p>
      <ActionForm action={login} className="mt-6 space-y-4">
        <input type="hidden" name="next" value={next} />
        <Field label="Email"><input className="input" name="email" type="email" autoComplete="email" required /></Field>
        <Field label="Password"><input className="input" name="password" type="password" autoComplete="current-password" required /></Field>
        <p className="-mt-2 text-right text-xs"><Link className="link" href="/forgot">Forgot password?</Link></p>
        <Submit className="w-full">Sign in</Submit>
      </ActionForm>
      <p className="mt-6 text-center text-sm text-muted">
        New here? <Link className="link" href={`/signup${next ? `?next=${encodeURIComponent(next)}` : ""}`}>Create an account</Link>
      </p>
    </>
  );
}
