import Link from "next/link";
import { redirect } from "next/navigation";
import { createWorkspace } from "@/app/actions";
import { ActionForm, Submit } from "@/components/ActionForm";
import { Logo } from "@/components/Logo";
import { Field } from "@/components/ui";
import { getMe } from "@/lib/me";

export const metadata = { title: "Set up your program" };

export default async function Onboarding({ searchParams }: { searchParams: Promise<{ new?: string }> }) {
  const me = await getMe("/onboarding");
  const another = (await searchParams).new !== undefined && me.merchants.length > 0;
  if (me.merchant && !another) redirect("/dashboard");
  return (
    <div className="mx-auto max-w-lg px-4 py-12">
      <Logo href="/home" />
      <h1 className="mt-10 page-title">{another ? "Add another program" : "Set up your affiliate program"}</h1>
      <p className="mt-2 text-sm text-muted">
        {another ? "Each program has its own Stripe account, affiliates, commission rules and portal domain." : "You can connect Stripe and tune commission rules in the next step."}
      </p>
      <ActionForm action={createWorkspace} className="card mt-6 space-y-4" secretLabel="Your server API key">
        <Field label="Product name"><input className="input" name="name" placeholder="Acme" required /></Field>
        <Field label="Website" hint="Affiliate links point here."><input className="input" name="website" type="url" placeholder="https://acme.com" required /></Field>
        <div className="flex items-center gap-3">
          <Submit>Create program</Submit>
          <Link className="link text-sm" href="/dashboard">Go to dashboard →</Link>
        </div>
      </ActionForm>
      <p className="mt-6 text-sm text-muted">
        Here to promote someone else&apos;s product? Open the join link they gave you{me.affiliations ? <>, or go to <Link className="link" href="/a">your programs</Link></> : ""}.
      </p>
    </div>
  );
}
