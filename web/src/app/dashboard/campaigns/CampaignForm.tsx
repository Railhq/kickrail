"use client";

import { useState } from "react";
import { saveCampaign } from "@/app/actions";
import { ActionForm, Submit } from "@/components/ActionForm";
import { Field } from "@/components/ui";
import type { Campaign, Rule } from "@/lib/types";

type Row = { match: "product" | "price"; id: string; label: string; type: "percent" | "flat" | "none"; percent: string; flat: string; currency: string };

function toRow(r: { match: "product" | "price"; id: string; label: string; rule: Rule }): Row {
  const x = r.rule;
  return { match: r.match, id: r.id, label: r.label, type: x.type, percent: x.type === "percent" ? String(x.bps / 100) : "", flat: x.type === "flat" ? String(x.cents / 100) : "", currency: x.type === "flat" ? x.currency : "usd" };
}

export type Coupon = { id: string; name: string | null; percent_off: number | null; amount_off: number | null; currency: string | null };

function couponLabel(c: Coupon) {
  const off = c.percent_off ? `${c.percent_off}% off` : c.amount_off ? `${(c.amount_off / 100).toFixed(2)} ${c.currency?.toUpperCase()} off` : "";
  return `${c.name ?? c.id}${off && c.name !== off ? ` (${off})` : ""}`;
}

export function CampaignForm({ campaign, coupons, website }: { campaign?: Campaign; coupons: Coupon[] | null; website: string }) {
  const [isPublic, setPublic] = useState(campaign?.public ?? false);
  const [rule, setRule] = useState(campaign?.rule.type ?? "percent");
  const [mode, setMode] = useState(campaign?.duration.mode ?? "months");
  const [rows, setRows] = useState<Row[]>(campaign?.product_rules.map(toRow) ?? []);
  const [kind, setKind] = useState<"cash" | "custom">(campaign?.reward?.type ?? "cash");
  const reward = campaign?.reward;
  const set = (i: number, patch: Partial<Row>) => setRows(rows.map((x, j) => (j === i ? { ...x, ...patch } : x)));
  const r = campaign?.rule;
  const d = campaign?.duration;
  return (
    <ActionForm action={saveCampaign} className="grid gap-4 sm:grid-cols-2">
      {campaign && <input type="hidden" name="id" value={campaign.id} />}
      <Field label="Name"><input className="input" name="name" defaultValue={campaign?.name ?? ""} placeholder="Creators" required /></Field>
      <Field label="Reward" hint={kind === "custom" ? "Anything that isn't cash: a discount, a free month, swag. Kickrail records who earned it and sends a reward.earned webhook; you hand it out." : "A share of what referred customers pay, paid out in cash."}>
        <select className="input" name="reward_type" value={kind} onChange={(e) => setKind(e.target.value as "cash" | "custom")}>
          <option value="cash">Cash commission</option>
          <option value="custom">Custom reward</option>
        </select>
      </Field>
      {kind === "custom" ? (
        <>
          <div className="grid gap-4 rounded-lg border border-line bg-sunk/40 p-3 sm:col-span-2 sm:grid-cols-2">
            <Field label="Affiliate gets"><input className="input" name="affiliate_reward" defaultValue={reward?.affiliate.description ?? ""} placeholder="50% off forever" maxLength={120} required /></Field>
            <Field label="When">
              <div className="flex gap-2">
                <select className="input" name="affiliate_reward_on" defaultValue={reward?.affiliate.on ?? "first_payment"}>
                  <option value="signup">A referral signs up</option>
                  <option value="first_payment">A referral first pays</option>
                  <option value="every_payment">Every payment from a referral</option>
                </select>
                <select className="input w-44" name="affiliate_reward_limit" defaultValue={reward?.affiliate.limit ?? "per_referral"} aria-label="How often">
                  <option value="per_referral">Every time</option>
                  <option value="once">Once per affiliate</option>
                </select>
              </div>
            </Field>
            <Field label="Referred customer gets" hint="Optional. Leave empty if only the affiliate is rewarded."><input className="input" name="customer_reward" defaultValue={reward?.customer?.description ?? ""} placeholder="25% off" maxLength={120} /></Field>
            <Field label="When">
              <select className="input" name="customer_reward_on" defaultValue={reward?.customer?.on ?? "signup"}>
                <option value="signup">They sign up</option>
                <option value="first_payment">They first pay</option>
              </select>
            </Field>
          </div>
          {/* The cash settings are kept as they were, for switching back. */}
          <input type="hidden" name="rule_type" value={r?.type ?? "percent"} />
          <input type="hidden" name="percent" value={r?.type === "percent" ? r.bps / 100 : 30} />
          <input type="hidden" name="flat" value={r?.type === "flat" ? r.cents / 100 : ""} />
          <input type="hidden" name="currency" value={r?.type === "flat" ? r.currency : "usd"} />
          <input type="hidden" name="duration_mode" value={d?.mode ?? "months"} />
          <input type="hidden" name="months" value={d?.mode === "months" ? d.months : 12} />
          <input type="hidden" name="hold_days" value={campaign?.hold_days ?? 30} />
          <input type="hidden" name="min_payout" value={campaign ? campaign.min_payout_cents / 100 : 50} />
          <input type="hidden" name="product_rules" value={JSON.stringify(rows)} />
        </>
      ) : (
      <>
      <Field label="Commission">
        <div className="flex gap-2">
          <select className="input w-32" name="rule_type" value={rule} onChange={(e) => setRule(e.target.value as "percent" | "flat")}>
            <option value="percent">Percent</option>
            <option value="flat">Flat</option>
          </select>
          {rule === "percent" ? (
            <div className="relative flex-1">
              <input className="input pr-8" name="percent" type="number" step="0.01" min="0.01" max="100" defaultValue={r?.type === "percent" ? r.bps / 100 : 30} required />
              <span className="absolute right-3 top-2 text-sm text-muted">%</span>
            </div>
          ) : (
            <>
              <input className="input flex-1" name="flat" type="number" step="0.01" min="0.01" defaultValue={r?.type === "flat" ? r.cents / 100 : 20} required />
              <input className="input w-20 uppercase" name="currency" defaultValue={r?.type === "flat" ? r.currency : "usd"} maxLength={3} />
            </>
          )}
        </div>
      </Field>
      <Field label="Paid on">
        <div className="flex gap-2">
          <select className="input" name="duration_mode" value={mode} onChange={(e) => setMode(e.target.value as "once" | "months" | "forever")}>
            <option value="once">First payment only</option>
            <option value="months">Payments for N months</option>
            <option value="forever">Every payment, forever</option>
          </select>
          {mode === "months" && <input className="input w-24" name="months" type="number" min="1" max="120" defaultValue={d?.mode === "months" ? d.months : 12} required />}
        </div>
      </Field>
      <Field label="Hold period (days)" hint="Commissions become payable this long after the payment, so refunds can land first.">
        <input className="input" name="hold_days" type="number" min="0" max="180" defaultValue={campaign?.hold_days ?? 30} />
      </Field>
      <Field label="Minimum payout" hint="Affiliates below this carry their balance to the next payout.">
        <input className="input" name="min_payout" type="number" min="0" step="0.01" defaultValue={campaign ? campaign.min_payout_cents / 100 : 50} />
      </Field>
      </>
      )}
      <Field label="Creator-code coupon" hint={coupons ? "Each affiliate's code becomes a Stripe promotion code for this coupon, so customers can type it at checkout." : "Connect Stripe to turn affiliate codes into checkout promotion codes."}>
        <select className="input" name="stripe_coupon_id" defaultValue={campaign?.stripe_coupon_id ?? ""} disabled={!coupons}>
          <option value="">No discount (codes are tracking only)</option>
          {coupons?.map((c) => <option key={c.id} value={c.id}>{couponLabel(c)}</option>)}
        </select>
      </Field>
      {kind === "cash" && (
        <Field label="Signup bounty" hint="A flat amount for every referred signup, paid or not. Leave empty for none.">
          <div className="flex gap-2">
            <input className="input flex-1" name="lead_bounty" type="number" step="0.01" min="0" placeholder="0.00" defaultValue={campaign?.lead_bounty ? campaign.lead_bounty.cents / 100 : ""} />
            <input className="input w-20 uppercase" name="lead_bounty_currency" defaultValue={campaign?.lead_bounty?.currency ?? "usd"} maxLength={3} />
          </div>
        </Field>
      )}
      <div className="rounded-lg border border-line bg-sunk/40 p-3 sm:col-span-2">
        <label className="flex items-start gap-2 text-sm">
          <input type="checkbox" name="public" className="mt-1" checked={isPublic} onChange={(e) => setPublic(e.target.checked)} />
          <span>
            <span className="font-medium">Public join page</span>
            <span className="block text-xs text-muted">
              {campaign?.is_default
                ? "Your main join page always signs people up to the default campaign. Turn this on to also give it a page of its own."
                : "Anyone with the link can sign up straight into this campaign. Leave it off for an invite-only campaign: you add people from the Affiliates page."}
            </span>
          </span>
        </label>
        {isPublic && (
          <div className="mt-3">
            <Field label="Page name" hint="The last part of the join page address. Leave empty to use the campaign name.">
              <input className="input font-mono" name="slug" defaultValue={campaign?.slug ?? ""} placeholder="partners" pattern="[a-z0-9][a-z0-9\-]{1,39}" maxLength={40} />
            </Field>
          </div>
        )}
        {!isPublic && campaign?.slug && <input type="hidden" name="slug" value={campaign.slug} />}
      </div>
      <Field label="Landing page" hint={`Where this campaign's affiliate links send people. Leave empty for ${website}. Must be on the same site.`}>
        <input className="input" name="landing_url" type="url" defaultValue={campaign?.landing_url ?? ""} placeholder={`${website}/partners`} />
      </Field>
      {kind === "cash" && <div className="sm:col-span-2">
        <p className="text-sm font-medium">Product rules</p>
        <p className="mt-0.5 text-xs text-muted">Pay a different rate on specific Stripe products or prices. A matching rule beats the campaign rate and any per-affiliate rate. Lines without a match use the rate above.</p>
        <input type="hidden" name="product_rules" value={JSON.stringify(rows)} />
        <div className="mt-2 space-y-2">
          {rows.map((x, i) => (
            <div key={i} className="flex flex-wrap items-center gap-2 rounded-lg border border-line bg-sunk/40 p-2">
              <select className="input w-28" value={x.match} onChange={(e) => set(i, { match: e.target.value as Row["match"] })} aria-label="Match">
                <option value="product">Product</option>
                <option value="price">Price</option>
              </select>
              <input className="input w-48 font-mono text-xs" value={x.id} onChange={(e) => set(i, { id: e.target.value })} placeholder={x.match === "product" ? "prod_…" : "price_…"} aria-label="Stripe id" />
              <input className="input w-36" value={x.label} onChange={(e) => set(i, { label: e.target.value })} placeholder="Label" aria-label="Label" />
              <select className="input w-28" value={x.type} onChange={(e) => set(i, { type: e.target.value as Row["type"] })} aria-label="Rule">
                <option value="percent">Percent</option>
                <option value="flat">Flat</option>
                <option value="none">Nothing</option>
              </select>
              {x.type === "percent" && <input className="input w-20" type="number" step="0.01" min="0.01" max="100" value={x.percent} onChange={(e) => set(i, { percent: e.target.value })} placeholder="%" aria-label="Percent" />}
              {x.type === "flat" && (
                <>
                  <input className="input w-24" type="number" step="0.01" min="0.01" value={x.flat} onChange={(e) => set(i, { flat: e.target.value })} placeholder="Amount" aria-label="Amount" />
                  <input className="input w-16 uppercase" value={x.currency} onChange={(e) => set(i, { currency: e.target.value })} maxLength={3} aria-label="Currency" />
                </>
              )}
              <button type="button" className="ml-auto text-xs text-red-700 hover:underline" onClick={() => setRows(rows.filter((_, j) => j !== i))}>remove</button>
            </div>
          ))}
        </div>
        <button type="button" className="btn btn-secondary mt-2" onClick={() => setRows([...rows, { match: "product", id: "", label: "", type: "percent", percent: "20", flat: "", currency: "usd" }])}>
          Add product rule
        </button>
      </div>}
      <div className="sm:col-span-2"><Submit>{campaign ? "Save changes" : "Create campaign"}</Submit></div>
    </ActionForm>
  );
}
