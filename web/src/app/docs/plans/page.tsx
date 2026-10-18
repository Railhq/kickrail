import type { Metadata } from "next";
import Link from "next/link";
import { PLANS, UNLIMITED } from "@/lib/plans";
import { H2, List, Note, P, Title } from "../ui";

export const metadata: Metadata = { title: "Plans and limits" };

const n = (v: number) => (v >= UNLIMITED ? "Unlimited" : String(v));
const yes = (v: boolean) => (v ? "Yes" : "No");

const ROWS: [string, (p: (typeof PLANS)[number]) => string][] = [
  ["Price", (p) => (p.month ? `$${p.month}/mo or $${p.year.toLocaleString("en-US")}/yr` : "Free")],
  ["Affiliate revenue covered", (p) => `$${p.revenue_cap.toLocaleString("en-US")}/mo`],
  ["Transaction fee", () => "0%"],
  ["Campaigns", (p) => n(p.campaigns)],
  ["Teammates", (p) => n(p.teammates)],
  ["Custom portal domains", (p) => String(p.domains)],
  ["Creator codes", (p) => yes(p.creator_codes)],
  ["Report signups (POST /v1/referrals)", () => "Yes"],
  ["Full API and webhooks", (p) => yes(p.api)],
  ["Stripe payouts", (p) => yes(p.stripe_payouts)],
  ["Kickrail branding on the portal", (p) => (p.branding ? "Shown" : "Removed")],
  ["Priority support", (p) => yes(p.priority_support)],
];

export default function Plans() {
  return (
    <>
      <Title eyebrow="Running a program" lead="Plans are a flat monthly price per program, with no cut of your sales. Every new program gets a 14-day Growth trial, no card needed.">
        Plans and limits
      </Title>

      <div className="overflow-x-auto rounded-xl border border-line bg-surface">
        <table className="w-full min-w-[640px] text-left text-sm">
          <thead className="border-b border-line">
            <tr>
              <th className="px-4 py-3" />
              {PLANS.map((p) => <th key={p.id} className="px-4 py-3 font-medium">{p.name}</th>)}
            </tr>
          </thead>
          <tbody>
            {ROWS.map(([label, f]) => (
              <tr key={label} className="border-b border-line last:border-0">
                <td className="px-4 py-2.5 text-muted">{label}</td>
                {PLANS.map((p) => <td key={p.id} className="px-4 py-2.5">{f(p)}</td>)}
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      <H2>Affiliate revenue</H2>
      <P>Affiliate revenue is what referred customers paid you in a calendar month (before tax), converted to US dollars. It is what decides the plan that fits; your other revenue doesn&apos;t count.</P>
      <List>
        <li>Going over never stops tracking or commissions.</li>
        <li>If you are over for two full months in a row, the dashboard shows a notice and the owner gets one email a month suggesting the plan that fits.</li>
        <li>Over $150,000 a month on Scale, get in touch for custom pricing.</li>
      </List>

      <H2>Trial, upgrades and downgrades</H2>
      <List>
        <li>The trial gives you everything in Growth for 14 days. If you don&apos;t pick a plan, the program moves to Free when it ends and keeps tracking.</li>
        <li>Choosing a paid plan during the trial keeps the rest of the trial; the first charge is when it ends.</li>
        <li>Switching between paid plans takes effect immediately, prorated.</li>
        <li>On a downgrade, everything you already have keeps running: extra campaigns, teammates and domains. You just can&apos;t add more until you are within the new plan.</li>
        <li>The owner manages the plan and invoices under Billing in the dashboard. Yearly plans cost 10 months.</li>
      </List>
      <Note title="What happens without the plan">
        Anything a plan doesn&apos;t include returns <b>402 Payment Required</b> from the API with a message naming the plan you need, and the dashboard shows an upgrade prompt. Reporting signups and lookups always work.
      </Note>
      <P><Link className="link" href="/#pricing">Compare plans on the pricing page</Link>.</P>
    </>
  );
}
