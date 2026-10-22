import Link from "next/link";
import { notFound } from "next/navigation";
import { addCode, addMerchantLink, deleteCode, deleteMerchantLink, setRateOverride, updateAffiliate } from "@/app/actions";
import { ActionForm, Submit } from "@/components/ActionForm";
import { PortalView } from "@/components/PortalView";
import { Badge, Card, Field } from "@/components/ui";
import { api, authed } from "@/lib/backend";
import type { Affiliate, Campaign, PortalView as View } from "@/lib/types";
import { AffiliateCommissions } from "./AffiliateCommissions";
import { RateFields } from "./RateFields";

export const metadata = { title: "Affiliate" };

export default async function AffiliateDetail({ params, searchParams }: { params: Promise<{ id: string }>; searchParams: Promise<{ tab?: string; page?: string }> }) {
  const { id } = await params;
  const sp = await searchParams;
  const [view, a, campaigns] = await Promise.all([
    authed<View & { affiliate: { name: string; email: string } }>(`/merchant/affiliates/${id}/view`, `/dashboard/affiliates/${id}`),
    authed<Affiliate>(`/merchant/affiliates/${id}`, `/dashboard/affiliates/${id}`),
    api<Campaign[]>("/merchant/campaigns"),
  ]);
  if (!view || !a) notFound();
  const campaign = campaigns.find((c) => c.id === a.campaign_id);
  const o = a.rate_override;

  return (
    <div className="space-y-8">
      <div>
        <Link href="/dashboard/affiliates" className="eyebrow hover:text-fg">← Affiliates</Link>
        <h1 className="page-title mt-3">{view.affiliate.name || view.affiliate.email}</h1>
        <p className="text-sm text-muted">{view.affiliate.email}{a.tax_form && <> · tax form <Badge tone="green">{a.tax_form.toUpperCase().replace("W8", "W-8").replace("W9", "W-9")}</Badge></>}</p>
      </div>

      <div className="grid gap-6 lg:grid-cols-2">
        <Card title="Commission rate">
          <p className="mb-4 text-sm text-muted">
            Campaign <b>{campaign?.name}</b> pays {campaign?.description}.{" "}
            {a.rate_override_description ? <>This affiliate gets <b>{a.rate_override_description}</b> instead.</> : "No override."} Product rules on the campaign still take priority.
          </p>
          <ActionForm action={setRateOverride} className="space-y-3">
            <input type="hidden" name="id" value={a.id} />
            <RateFields
              defaultType={o ? o.type : "campaign"}
              defaultPercent={o?.type === "percent" ? o.bps / 100 : 40}
              defaultFlat={o?.type === "flat" ? o.cents / 100 : 25}
              defaultCurrency={o?.type === "flat" ? o.currency : "usd"}
              withCampaign
            />
            <Submit variant="secondary">Save rate</Submit>
          </ActionForm>
          <ActionForm action={updateAffiliate} className="mt-5 flex flex-wrap items-end gap-2 border-t border-line pt-4">
            <input type="hidden" name="id" value={a.id} />
            <Field label="Campaign">
              <select name="campaign_id" defaultValue={a.campaign_id} className="input">
                {campaigns.map((c) => <option key={c.id} value={c.id}>{c.name}</option>)}
              </select>
            </Field>
            <Submit variant="secondary">Move</Submit>
          </ActionForm>
        </Card>

        <Card title="Links and codes">
          <ul className="space-y-2 text-sm">
            <li className="flex items-center justify-between gap-2">
              <span className="truncate font-mono text-xs">{view.link}</span>
              <span className="text-xs text-muted">main</span>
            </li>
            {a.links.map((l) => (
              <li key={l.id} className="flex items-center justify-between gap-2">
                <span className="min-w-0 truncate font-mono text-xs" title={l.url}>{l.url}</span>
                <form action={deleteMerchantLink.bind(null, a.id, l.id)}><button className="text-xs text-red-700 hover:underline">remove</button></form>
              </li>
            ))}
          </ul>
          <ActionForm action={addMerchantLink} className="mt-3 grid gap-2 sm:grid-cols-[8rem_1fr_auto]">
            <input type="hidden" name="id" value={a.id} />
            <input className="input font-mono" name="token" placeholder="jane-blog" pattern="[a-z0-9_\-]{3,32}" required aria-label="Link name" />
            <input className="input" name="landing_url" type="url" placeholder="Landing page (optional)" aria-label="Landing page" />
            <Submit variant="secondary">Add link</Submit>
          </ActionForm>

          <div className="mt-5 border-t border-line pt-4">
            <div className="flex flex-wrap gap-2 text-sm">
              {a.code && <Badge tone={a.stripe_promotion_code === a.code ? "green" : "gray"}>{a.code}</Badge>}
              {a.codes.map((c) => (
                <span key={c.id} className="inline-flex items-center gap-1">
                  <Badge tone={c.redeemable_at_checkout ? "green" : "gray"}>{c.code}</Badge>
                  <form action={deleteCode.bind(null, a.id, c.id)}><button className="text-xs text-red-700" aria-label={`Remove ${c.code}`}>×</button></form>
                </span>
              ))}
              {!a.code && a.codes.length === 0 && <span className="text-muted">No codes yet.</span>}
            </div>
            <ActionForm action={addCode} className="mt-3 flex gap-2">
              <input type="hidden" name="id" value={a.id} />
              <input className="input font-mono uppercase" name="code" placeholder="JANE20" pattern="[A-Za-z0-9]{3,20}" required aria-label="Code" />
              <Submit variant="secondary">Add code</Submit>
            </ActionForm>
            <p className="mt-2 text-xs text-muted">Green codes are Stripe promotion codes on the campaign coupon, so customers can type them at checkout.</p>
          </div>
        </Card>
      </div>

      <AffiliateCommissions affiliateId={id} tab={sp.tab} page={Math.max(1, Number.parseInt(sp.page ?? "1", 10) || 1)} />

      <section>
        <div className="mb-4 flex flex-wrap items-center gap-3 rounded-xl border border-ink bg-ink px-4 py-3 text-sm text-stone-200">
          <span className="h-2 w-2 rounded-full bg-signal" />
          <span>
            <b className="text-white">Viewing as {view.affiliate.name || view.affiliate.email}.</b> This is their portal exactly as they see it, read-only.
          </span>
        </div>
        <div className="rounded-2xl border border-dashed border-stone-300 p-4 sm:p-6">
          <PortalView d={view} preview />
        </div>
      </section>
    </div>
  );
}
