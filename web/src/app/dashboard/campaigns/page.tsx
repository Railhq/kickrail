import { makeDefaultCampaign } from "@/app/actions";
import { CopyButton } from "@/components/CopyButton";
import { Badge, Card } from "@/components/ui";
import { api } from "@/lib/backend";
import { money } from "@/lib/format";
import type { Campaign, Merchant } from "@/lib/types";
import { CampaignForm, type Coupon } from "./CampaignForm";

export const metadata = { title: "Campaigns" };

export default async function CampaignsPage() {
  const [campaigns, m] = await Promise.all([api<Campaign[]>("/merchant/campaigns"), api<Merchant>("/merchant")]);
  const coupons = m.stripe ? await api<Coupon[]>("/merchant/stripe/coupons").catch(() => null) : null;
  return (
    <div className="space-y-6">
      <h1 className="page-title">Campaigns</h1>
      <p className="text-sm text-muted">People who sign up on your main join page join the default campaign. A public campaign has its own join page, so you can recruit partners or creators onto different terms; a private one is invite-only. Give an individual affiliate a custom rate (for example, a creator on a 50% deal) from their page under Affiliates. Rule changes apply to future commissions only.</p>
      {campaigns.map((c) => (
        <Card
          key={c.id}
          title={<span className="flex items-center gap-2">{c.name}{c.is_default && <Badge tone="green">default</Badge>}{c.public ? <Badge tone="blue">public</Badge> : !c.is_default && <Badge>private</Badge>}</span>}
          actions={!c.is_default && <form action={makeDefaultCampaign.bind(null, c.id)}><button className="btn btn-secondary">Make default</button></form>}
        >
          <p className="text-sm text-muted">{c.description} · {c.hold_days}-day hold · {money(c.min_payout_cents)} minimum{c.lead_bounty && ` · ${money(c.lead_bounty.cents, c.lead_bounty.currency)} per signup`}</p>
          {c.product_rules.length > 0 && (
            <ul className="mt-2 space-y-0.5 text-sm">
              {c.product_rules.map((r) => <li key={r.id}><span className="font-mono text-xs text-muted">{r.id}</span> {r.label && <b>{r.label}</b>}: {r.description}</li>)}
            </ul>
          )}
          {c.join_url && (
            <p className="mt-2 flex flex-wrap items-center gap-2 text-sm">
              Join page: <a className="link font-mono text-xs" href={c.join_url} target="_blank" rel="noopener">{c.join_url}</a> <CopyButton text={c.join_url} />
            </p>
          )}
          {c.landing_url && <p className="mt-1 text-sm text-muted">Links point to <span className="font-mono text-xs">{c.landing_url}</span></p>}
          <div className="mb-4" />
          <details>
            <summary className="cursor-pointer text-sm font-medium text-brand">Edit</summary>
            <div className="mt-4"><CampaignForm campaign={c} coupons={coupons} website={m.website} /></div>
          </details>
        </Card>
      ))}
      <Card title="New campaign"><CampaignForm coupons={coupons} website={m.website} /></Card>
    </div>
  );
}
