import Link from "next/link";
import { Card, Notice, Stat, StatGroup } from "@/components/ui";
import { CopyButton } from "@/components/CopyButton";
import { api, siteUrl } from "@/lib/backend";
import { mainCurrency, splitMoney } from "@/lib/format";
import type { Merchant } from "@/lib/types";

type Overview = {
  affiliates: number; pending_affiliates: number; clicks: number; leads: number; customers: number; flagged: number;
  referred_revenue: Record<string, number>; commissions: Record<string, Record<string, number>>;
  stripe_connected: boolean; installed: boolean;
};

export const metadata = { title: "Overview" };

export default async function OverviewPage() {
  const [o, m] = await Promise.all([api<Overview>("/merchant/overview"), api<Merchant>("/merchant")]);
  const joinUrl = `${await siteUrl()}/join/${m.slug}`;
  const steps = [
    { done: o.stripe_connected, title: "Connect Stripe", body: <>So Kickrail can see your payments. <Link className="link" href="/dashboard/settings">Settings →</Link></> },
    { done: o.installed, title: "Install tracking", body: <>Add the script to your site, then report signups from your server. <Link className="link" href="/dashboard/settings#install">Install guide →</Link></> },
    { done: o.affiliates > 0, title: "Invite affiliates", body: <>Share your program page: <code className="text-xs">/join/{m.slug}</code></> },
  ];
  const funnel = [
    { label: "Clicks", value: o.clicks },
    { label: "Signups", value: o.leads },
    { label: "Paying customers", value: o.customers },
  ];
  const rate = (a: number, b: number) => (a ? `${((b / a) * 100).toFixed(b / a < 0.1 ? 1 : 0)}%` : "n/a");
  const cur = mainCurrency(o.referred_revenue, o.commissions.pending, o.commissions.paid);
  const [revenue, owed, paid] = [o.referred_revenue, o.commissions.pending, o.commissions.paid].map((m) => splitMoney(m, cur));
  const done = steps.filter((s) => s.done).length;
  return (
    <div className="space-y-8">
      <header className="flex flex-wrap items-end justify-between gap-4">
        <div>
          <p className="eyebrow">{m.name}</p>
          <h1 className="page-title mt-2">Overview</h1>
        </div>
        <p className="text-sm text-muted">
          <span className="num font-medium text-fg">{o.affiliates}</span> active affiliate{o.affiliates === 1 ? "" : "s"}
          {o.pending_affiliates > 0 && (
            <>
              {" · "}
              <Link className="link" href="/dashboard/affiliates">{o.pending_affiliates} awaiting approval</Link>
            </>
          )}
        </p>
      </header>

      {steps.some((s) => !s.done) && (
        <Card title="Get set up" actions={<span className="num text-xs text-muted">{done}/{steps.length} done</span>}>
          <ol className="grid gap-4 sm:grid-cols-3">
            {steps.map((s, i) => (
              <li key={s.title} className={`rounded-xl border p-4 ${s.done ? "border-line bg-sunk/40" : "border-ink/80"}`}>
                <span className={`num flex h-6 w-6 items-center justify-center rounded-md text-xs ${s.done ? "bg-emerald-600 text-white" : "bg-ink text-signal"}`}>{s.done ? "✓" : i + 1}</span>
                <p className={`mt-3 text-sm font-medium ${s.done ? "text-muted line-through" : ""}`}>{s.title}</p>
                {!s.done && <p className="mt-1 text-sm text-muted">{s.body}</p>}
              </li>
            ))}
          </ol>
        </Card>
      )}

      {o.flagged > 0 && (
        <Notice>
          {o.flagged} referral{o.flagged === 1 ? " looks" : "s look"} like self-referral. Their commissions are on hold until you review them.{" "}
          <Link className="link" href="/dashboard/referrals?flagged=1">Review →</Link>
        </Notice>
      )}

      <section>
        <h2 className="eyebrow mb-3">Money</h2>
        <StatGroup cols={3}>
          <Stat big label="Referred revenue" value={revenue.main} sub={revenue.rest} hint="Paid by customers your affiliates sent" />
          <Stat big label="Commissions owed" value={owed.main} sub={owed.rest} hint={<Link className="link" href="/dashboard/payouts">Pay affiliates →</Link>} />
          <Stat big label="Commissions paid" value={paid.main} sub={paid.rest} hint="All time" />
        </StatGroup>
      </section>

      <section>
        <h2 className="eyebrow mb-3">Funnel</h2>
        <div className="grid overflow-hidden rounded-2xl border border-line bg-surface sm:grid-cols-3">
          {funnel.map((f, i) => {
            const pct = funnel[0].value ? Math.max(4, (f.value / funnel[0].value) * 100) : 0;
            return (
              <div key={f.label} className={`relative border-line py-5 pr-5 ${i > 0 ? "pl-5 sm:pl-9" : "pl-5"} max-sm:border-t max-sm:first:border-t-0 sm:border-l sm:first:border-l-0`}>
                {i > 0 && (
                  <span className="num absolute -left-px top-5 hidden -translate-x-1/2 rounded-md border border-line bg-surface px-1.5 py-0.5 text-[11px] text-muted sm:block">
                    {rate(funnel[i - 1].value, f.value)}
                  </span>
                )}
                <p className="eyebrow">{f.label}</p>
                <p className="num mt-2 text-3xl font-medium">{f.value.toLocaleString()}</p>
                <div className="mt-4 h-1.5 rounded-full bg-sunk">
                  <div className="h-full rounded-full bg-ink" style={{ width: `${pct}%` }} />
                </div>
              </div>
            );
          })}
        </div>
      </section>

      <section className="flex flex-wrap items-center justify-between gap-4 rounded-2xl bg-ink px-5 py-4 text-stone-200">
        <div className="min-w-0">
          <p className="font-mono text-[11px] uppercase tracking-[0.12em] text-ink-muted">Your program page</p>
          <p className="mt-1 truncate font-mono text-sm text-white">{joinUrl}</p>
        </div>
        <CopyButton text={joinUrl} />
      </section>
    </div>
  );
}
