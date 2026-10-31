import Link from "next/link";
import { movePass, openBillingPortal, startCheckout } from "@/app/actions";
import { ActionForm, Submit } from "@/components/ActionForm";
import { Badge, Card, Notice } from "@/components/ui";
import { api } from "@/lib/backend";
import { date, money } from "@/lib/format";
import { planFeatures, UNLIMITED } from "@/lib/plans";
import type { BillingInfo, PassWorkspaces, PlanSummary } from "@/lib/types";

export const metadata = { title: "Billing" };

function statusLine(p: PlanSummary) {
  if (p.comped) return "Kickrail is free for this program.";
  if (p.source === "pass") return `Included in your Railhq Pass: ${p.name} at no charge while the owner's Pass is active and covers this program.`;
  if (p.status === "trialing" && p.trial_ends_at) {
    const days = Math.max(0, Math.ceil((new Date(p.trial_ends_at).getTime() - Date.now()) / 86_400_000));
    return p.subscribed ? `Trial: your card is charged on ${date(p.trial_ends_at)}.` : `Free trial of ${p.name}: ${days} ${days === 1 ? "day" : "days"} left, no card needed. After that the program moves to Free unless you pick a plan.`;
  }
  if (p.status === "trial_ended") return "Your trial ended, so the program is on Free. Tracking keeps running; pick a plan to get the paid features back.";
  if (p.status === "past_due") return "Your last payment failed. Stripe retries automatically; update your card to keep this plan.";
  if (p.subscribed && p.current_period_end) return p.cancel_at_period_end ? `Cancels on ${date(p.current_period_end)}, then moves to Free.` : `Renews ${p.interval === "year" ? "yearly" : "monthly"} on ${date(p.current_period_end)}.`;
  return "No card on file.";
}

export default async function BillingPage({ searchParams }: { searchParams: Promise<{ interval?: string; done?: string }> }) {
  const sp = await searchParams;
  const interval = sp.interval === "year" ? "year" : "month";
  const b = await api<BillingInfo>("/merchant/billing");
  const pass = b.railhq_pass ? await api<PassWorkspaces>("/railhq/pass-workspaces") : null;
  const p = b.plan;
  const cap = b.usage.cap_cents;
  const pct = cap ? Math.min(100, Math.round((b.usage.this_month_cents / cap) * 100)) : 0;
  const pastMonths = b.usage.months.slice(1);
  return (
    <div className="space-y-6">
      <h1 className="page-title">Billing</h1>
      {sp.done && <Notice tone="signal">Thanks. Your plan updates here as soon as Stripe confirms the payment, usually within a few seconds.</Notice>}
      {p.over_limit && (
        <Notice>
          Affiliates brought in more than your plan covers for two months in a row. Nothing has stopped: tracking and commissions run as normal.
          {p.suggested_plan && ` The ${b.plans.find((x) => x.id === p.suggested_plan)?.name} plan fits your volume.`}
        </Notice>
      )}

      {b.railhq_pass && !b.railhq_pass.covered && <Notice><PassFull n={b.railhq_pass.workspaces} /></Notice>}

      <Card
        title={<span className="flex items-center gap-2">{p.name} plan {p.status === "trialing" && <Badge tone="amber">trial</Badge>}{p.status === "past_due" && <Badge tone="red">past due</Badge>}{p.comped && <Badge tone="green">comped</Badge>}</span>}
        actions={b.can_manage && p.subscribed && b.enabled && (
          <ActionForm action={openBillingPortal}><Submit variant="secondary">Invoices and card</Submit></ActionForm>
        )}
      >
        <p className="text-sm">{statusLine(p)}</p>
        <div className="mt-5">
          <div className="flex items-baseline justify-between text-sm">
            <span className="text-muted">Affiliate revenue this month</span>
            <span><span className="font-medium">{money(b.usage.this_month_cents)}</span>{cap != null && <span className="text-muted"> of {money(cap)}</span>}</span>
          </div>
          {cap != null && (
            <div className="mt-2 h-2 overflow-hidden rounded-full bg-sunk">
              <div className={`h-full rounded-full ${pct >= 100 ? "bg-amber-500" : "bg-signal"}`} style={{ width: `${pct}%` }} />
            </div>
          )}
          <p className="mt-2 text-xs text-muted">
            {pastMonths.map((x) => `${x.month}: ${money(x.revenue_cents)}`).join(" · ")}. Revenue from referred customers, converted to USD at approximate rates. Going over never stops tracking; after two months over we suggest a bigger plan.
          </p>
        </div>
        <div className="mt-5 grid gap-3 text-sm sm:grid-cols-3">
          <Usage label="Campaigns" used={b.campaigns} limit={p.limits.campaigns} />
          <Usage label="Teammates" used={b.teammates} limit={p.limits.teammates} />
          <Usage label="Portal domains" used={b.domains} limit={p.limits.domains} />
        </div>
      </Card>

      {pass && pass.pass && <PassCard pass={pass} />}

      {!p.comped && (
        <>
          <div className="flex flex-wrap items-center justify-between gap-3">
            <h2 className="font-display text-2xl tracking-tight">Plans</h2>
            <div className="flex rounded-lg border border-line p-0.5 text-sm">
              <Link href="/dashboard/billing" className={`rounded-md px-3 py-1 ${interval === "month" ? "bg-ink text-white" : "text-muted"}`}>Monthly</Link>
              <Link href="/dashboard/billing?interval=year" className={`rounded-md px-3 py-1 ${interval === "year" ? "bg-ink text-white" : "text-muted"}`}>Yearly, 2 months free</Link>
            </div>
          </div>
          {!b.enabled && <Notice>Paid plans aren&apos;t switched on for this Kickrail instance yet.</Notice>}
          {b.enabled && !b.can_manage && <Notice>Only the program owner can change the plan.</Notice>}
          <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
            {b.plans.map((x) => {
              const current = x.id === p.id && (x.id === "free" ? !p.subscribed : p.subscribed && p.interval === interval);
              const price = interval === "year" ? x.year : x.month;
              return (
                <div key={x.id} className={`card flex flex-col p-5 ${x.id === p.id ? "ring-2 ring-signal" : ""}`}>
                  <p className="font-medium">{x.name}</p>
                  <p className="mt-2"><span className="font-display text-3xl">${price.toLocaleString("en-US")}</span><span className="text-sm text-muted">{x.id === "free" ? "" : interval === "year" ? "/yr" : "/mo"}</span></p>
                  <ul className="mt-4 flex-1 space-y-1.5 text-sm text-muted">
                    {planFeatures(x).map((f) => <li key={f}>{f}</li>)}
                  </ul>
                  <div className="mt-5">
                    {current ? (
                      <span className="btn btn-secondary w-full cursor-default opacity-70">Current plan</span>
                    ) : x.id === "free" ? (
                      p.subscribed && b.can_manage && b.enabled ? <ActionForm action={openBillingPortal}><Submit variant="secondary" className="w-full">Cancel to Free</Submit></ActionForm> : null
                    ) : b.enabled && b.can_manage ? (
                      <ActionForm action={startCheckout.bind(null, x.id, interval)}>
                        <Submit variant={x.id === "growth" ? "primary" : "secondary"} className="w-full">{p.subscribed ? `Switch to ${x.name}` : `Choose ${x.name}`}</Submit>
                      </ActionForm>
                    ) : null}
                  </div>
                </div>
              );
            })}
          </div>
          <p className="text-xs text-muted">Prices in USD, per program. 0% transaction fees on every plan. Plan changes are prorated. Downgrading never switches anything off: extra domains, teammates and campaigns keep working, you just can&apos;t add more.</p>
        </>
      )}
    </div>
  );
}

const UPGRADE = "https://accounts.getrailhq.com/billing";

function PassFull({ n }: { n: number }) {
  return (
    <>
      Your Pass covers {n} {n === 1 ? "workspace and it's" : "workspaces and they're"} in use. Move {n === 1 ? "it" : "one"} here, or upgrade at{" "}
      <a className="link" href={UPGRADE}>accounts.getrailhq.com/billing</a>.
    </>
  );
}

function PassCard({ pass }: { pass: PassWorkspaces }) {
  const covered = pass.programs.filter((x) => x.covered);
  const full = pass.used >= pass.workspaces;
  return (
    <Card title="Railhq Pass">
      <p className="text-sm">
        {pass.used} of {pass.workspaces} Pass {pass.workspaces === 1 ? "workspace" : "workspaces"} used. A covered program gets Starter at no charge; a paid plan above it wins.{" "}
        Need more? <a className="link" href={UPGRADE}>Upgrade your Pass</a>.
      </p>
      <ul className="mt-4 divide-y divide-line rounded-xl border border-line text-sm">
        {pass.programs.map((x) => (
          <li key={x.id} className="flex flex-wrap items-center justify-between gap-3 p-3">
            <span className="flex items-center gap-2">
              <span className="font-medium">{x.name}</span>
              {x.covered ? <Badge tone="green">covered</Badge> : <Badge>not covered</Badge>}
            </span>
            {!x.covered && (
              <ActionForm action={movePass.bind(null, x.id, covered.map((c) => c.id))} className="flex flex-wrap items-center gap-2">
                {full && covered.length > 0 && (
                  <select className="input w-auto" name="release" defaultValue={covered[covered.length - 1].id} aria-label="Program to take off the Pass">
                    {covered.map((c) => <option key={c.id} value={c.id}>Instead of {c.name}</option>)}
                  </select>
                )}
                <Submit variant="secondary">Move here</Submit>
              </ActionForm>
            )}
          </li>
        ))}
      </ul>
    </Card>
  );
}

function Usage({ label, used, limit }: { label: string; used: number; limit: number }) {
  return (
    <div className="rounded-xl border border-line p-3">
      <p className="text-muted">{label}</p>
      <p className="mt-1 font-medium">{used} <span className="font-normal text-muted">of {limit >= UNLIMITED ? "unlimited" : limit}</span></p>
    </div>
  );
}
