import Link from "next/link";
import { cookies } from "next/headers";
import { redirect } from "next/navigation";
import { login } from "@/app/actions";
import { ActionForm, Submit } from "@/components/ActionForm";
import { Field } from "@/components/ui";
import { api, partnerContext } from "@/lib/backend";
import { PARTNER_COOKIE, RAILHQ_TRIED_COOKIE, SESSION_COOKIE } from "@/lib/session";

export const metadata = { title: "Sign in" };

/** Whether the dashboard sign-in offers Railhq accounts (off unless the backend has it on). */
async function railhqOn(): Promise<boolean> {
  try {
    return (await api<{ railhq: boolean }>("/auth/railhq", { auth: false })).railhq;
  } catch {
    return false;
  }
}

export default async function Login({ searchParams }: { searchParams: Promise<{ next?: string; error?: string }> }) {
  const { next = "", error } = await searchParams;
  // Affiliates sign in here too, with their own login; Railhq is only for the dashboard.
  const railhq = !(await partnerContext(next)) && (await railhqOn());
  const q = next ? `?next=${encodeURIComponent(next)}` : "";
  if (railhq && !error) {
    const jar = await cookies();
    // Signed in to another Railhq app already: one silent round trip signs them in here.
    if (![SESSION_COOKIE, PARTNER_COOKIE, RAILHQ_TRIED_COOKIE].some((c) => jar.has(c))) redirect(`/auth/railhq/start?prompt=none&next=${encodeURIComponent(next || "/home")}`);
  }
  return (
    <>
      <h1 className="font-display text-3xl tracking-tight">Sign in</h1>
      <p className="mt-1 text-sm text-muted">One account for your program and every program you promote.</p>
      {error === "railhq" && <p className="mt-4 text-sm text-red-600">Signing in with Railhq didn&apos;t work. Try again, or use your email and password.</p>}
      {railhq && (
        <>
          <a className="btn btn-secondary mt-6 w-full" href={`/auth/railhq/start?prompt=login&next=${encodeURIComponent(next || "/home")}`}>Continue with Railhq</a>
          <p className="mt-4 text-center text-xs text-muted">or with your email</p>
        </>
      )}
      <ActionForm action={login} className={`${railhq ? "mt-4" : "mt-6"} space-y-4`}>
        <input type="hidden" name="next" value={next} />
        <Field label="Email"><input className="input" name="email" type="email" autoComplete="email" required /></Field>
        <Field label="Password"><input className="input" name="password" type="password" autoComplete="current-password" required /></Field>
        <p className="-mt-2 text-right text-xs"><Link className="link" href={`/forgot${q}`}>Forgot password?</Link></p>
        <Submit className="w-full">Sign in</Submit>
      </ActionForm>
      <p className="mt-6 text-center text-sm text-muted">
        New here? <Link className="link" href={`/signup${q}`}>Create an account</Link>
      </p>
    </>
  );
}
