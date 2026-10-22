import Link from "next/link";
import { notFound } from "next/navigation";
import { reviewReferral } from "@/app/actions";
import { CommissionTable } from "@/components/CommissionTable";
import { DeleteButton } from "@/components/DeleteButton";
import { Badge, Card, Empty, Notice, Stat, StatGroup, StatusBadge } from "@/components/ui";
import { api, authed } from "@/lib/backend";
import { date, displayMoney, type Fx, fxNote, referralSource, referralWho } from "@/lib/format";
import type { Commission, ReferralDetail } from "@/lib/types";

export const metadata = { title: "Referral" };

const sum = (rows: Commission[], pick: (c: Commission) => number) => {
  const out: Record<string, number> = {};
  for (const c of rows) out[c.currency] = (out[c.currency] ?? 0) + pick(c);
  return out;
};

function Row({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <div className="grid gap-1 py-2.5 sm:grid-cols-[9rem_1fr] sm:gap-4">
      <dt className="text-muted">{label}</dt>
      <dd className="min-w-0 break-words">{children}</dd>
    </div>
  );
}

export default async function ReferralPage({ params }: { params: Promise<{ id: string }> }) {
  const { id } = await params;
  const [r, fx] = await Promise.all([authed<ReferralDetail>(`/merchant/referrals/${id}`, `/dashboard/referrals/${id}`), api<Fx>("/merchant/fx")]);
  if (!r) notFound();
  const live = r.commissions.filter((c) => c.status !== "void");
  const revenue = sum(live, (c) => Math.max(c.base_cents, 0));
  const earned = sum(live, (c) => c.amount_cents);
  const paid = sum(live.filter((c) => c.status === "paid"), (c) => c.amount_cents);
  const [rev, ear, pd] = [revenue, earned, paid].map((m) => displayMoney(m, fx));
  const open = r.flags.length > 0 && !r.flags_cleared;
  const name = referralWho(r);
  const via = r.via?.code || r.via?.token || r.click?.token;
  const locked = r.commissions.some((c) => c.status === "paid" || c.payout_id);

  return (
    <div className="space-y-8">
      <div>
        <Link href="/dashboard/referrals" className="eyebrow hover:text-fg">← Referrals</Link>
        <h1 className="page-title mt-3 break-all">{name}</h1>
        <div className="mt-2 flex flex-wrap items-center gap-2 text-sm text-muted">
          <StatusBadge status={r.status} />
          {open && <Badge tone="amber">held</Badge>}
          {r.rejected && <Badge tone="red">rejected</Badge>}
          {r.test && <Badge>test</Badge>}
          <span>
            Signed up {date(r.created_at)}
            {r.first_paid_at && <> · first paid {date(r.first_paid_at)}</>}
          </span>
        </div>
      </div>

      {open && (
        <Notice>
          <p>This looks like a self-referral, so its commissions are held. Approving releases them; rejecting voids the unpaid ones.</p>
          <ul className="mt-1 list-disc pl-5">{r.flags.map((f) => <li key={f.kind}>{f.detail}</li>)}</ul>
          <div className="mt-3 flex gap-2">
            <form action={reviewReferral.bind(null, r.id, "clear")}><button className="btn btn-primary">Approve</button></form>
            <form action={reviewReferral.bind(null, r.id, "reject")}><button className="btn btn-danger">Reject</button></form>
          </div>
        </Notice>
      )}

      <StatGroup cols={3}>
        <Stat big label="Customer paid" value={rev.main} sub={rev.rest} hint="Payments that earned a commission" />
        <Stat big label="Commission earned" value={ear.main} sub={ear.rest} hint={`${live.length} commission${live.length === 1 ? "" : "s"}, after refunds`} />
        <Stat big label="Paid to affiliate" value={pd.main} sub={pd.rest} hint="So far" />
      </StatGroup>
      {[rev, ear, pd].some((b) => b.main.startsWith("≈") || b.rest?.startsWith("≈")) && <p className="-mt-6 text-xs text-muted">{fxNote(fx)}</p>}

      <div className="grid gap-6 lg:grid-cols-2">
        <Card title="Customer">
          <dl className="-my-2.5 divide-y divide-line text-sm">
            {r.email && <Row label="Email">{r.email}</Row>}
            {r.stripe_customer_id && <Row label="Stripe customer"><span className="font-mono text-xs">{r.stripe_customer_id}</span></Row>}
            {r.external_user_id && <Row label="Your user id"><span className="font-mono text-xs">{r.external_user_id}</span></Row>}
            <Row label="Signed up">{date(r.created_at)}</Row>
            <Row label="First paid">{r.first_paid_at ? date(r.first_paid_at) : <span className="text-muted">not yet</span>}</Row>
            {r.rewardful_id && <Row label="Rewardful id"><span className="font-mono text-xs">{r.rewardful_id}</span></Row>}
          </dl>
        </Card>

        <Card title="Referred by">
          <dl className="-my-2.5 divide-y divide-line text-sm">
            <Row label="Affiliate">
              <Link className="link" href={`/dashboard/affiliates/${r.affiliate.id}`}>{r.affiliate.name || r.affiliate.email}</Link>
              {r.affiliate.name && <p className="text-xs text-muted">{r.affiliate.email}</p>}
            </Row>
            {r.campaign && <Row label="Campaign">{r.campaign.name}</Row>}
            <Row label="How">{referralSource(r.source)}{via && <> · <span className="font-mono text-xs">{via}</span></>}</Row>
            {r.via?.url && <Row label="Link"><span className="font-mono text-xs">{r.via.url}</span></Row>}
            {r.click ? (
              <>
                <Row label="Clicked">{date(r.click.created_at)}</Row>
                {r.click.landing_url && <Row label="Landed on"><span className="font-mono text-xs">{r.click.landing_url}</span></Row>}
                <Row label="Came from">{r.click.referrer ? <span className="font-mono text-xs">{r.click.referrer}</span> : <span className="text-muted">direct or hidden by the browser</span>}</Row>
              </>
            ) : r.source === "rewardful" ? (
              <Row label="Click"><span className="text-muted">Rewardful doesn&apos;t export when they clicked, where they landed or where they came from.</span></Row>
            ) : null}
          </dl>
        </Card>
      </div>

      <section>
        <h2 className="eyebrow mb-3">Commissions</h2>
        <Card>
          {r.commissions.length === 0 ? <Empty>No commissions yet. They are created when this customer pays.</Empty> : <CommissionTable rows={r.commissions} withCustomer={false} />}
        </Card>
      </section>

      <div className="flex flex-wrap items-center justify-between gap-3 border-t border-line pt-6 text-sm text-muted">
        {locked ? (
          <p>This referral has paid commissions{r.commissions.some((c) => c.payout_id && c.status !== "paid") ? " or commissions in a payout" : ""}, so it can&apos;t be deleted. To stop it earning, reject it instead.</p>
        ) : (
          <>
            <p>Deleting removes this referral and its unpaid commissions. It&apos;s recorded in your audit log.</p>
            <DeleteButton kind="referrals" id={r.id} after="/dashboard/referrals" confirmText={`Delete the referral for ${name}, and its unpaid commissions? It's kept in your audit log. Add a reason (optional):`} />
          </>
        )}
      </div>
    </div>
  );
}
