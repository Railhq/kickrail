import Link from "next/link";
import { payCommissions } from "@/app/actions";
import { ActionForm, Submit } from "@/components/ActionForm";
import { CommissionTable } from "@/components/CommissionTable";
import { listHref, Pager } from "@/components/ListControls";
import { PickedTotal } from "@/components/PickedTotal";
import { Card, Empty } from "@/components/ui";
import { api } from "@/lib/backend";
import type { Commission, Page } from "@/lib/types";

const TABS = [
  { key: "due", label: "Due", query: "due=true", empty: "Nothing is due. Commissions become due when their hold period ends." },
  { key: "pending", label: "Pending", query: "due=false", empty: "Nothing pending." },
  { key: "paid", label: "Paid", query: "status=paid", empty: "Nothing paid yet." },
] as const;

/** One affiliate's commissions by Due, Pending and Paid, with ticked ones marked paid, due or not. */
export async function AffiliateCommissions({ affiliateId, tab, page }: { affiliateId: string; tab?: string; page: number }) {
  const path = `/dashboard/affiliates/${affiliateId}`;
  const active = TABS.find((t) => t.key === tab) ?? TABS[0];
  const lists = await Promise.all(
    TABS.map((t) => api<Page<Commission>>(`/merchant/commissions?affiliate_id=${encodeURIComponent(affiliateId)}&${t.query}&page=${t === active ? page : 1}`)),
  );
  const res = lists[TABS.indexOf(active)];
  const form = `pay-${affiliateId}`;
  const pickable = active.key !== "paid" && res.items.some((c) => !c.held && !c.payout_id);

  return (
    <section id="commissions" className="space-y-3">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <h2 className="eyebrow">Commissions</h2>
        <div className="flex flex-wrap gap-1 text-sm">
          {TABS.map((t, i) => (
            <Link key={t.key} href={`${listHref(path, { tab: t.key === "due" ? undefined : t.key })}#commissions`} className={`btn ${t === active ? "btn-primary" : "btn-secondary"}`}>
              {t.label} <span className="tabular-nums opacity-70">{lists[i].total.toLocaleString()}</span>
            </Link>
          ))}
        </div>
      </div>
      {active.key === "pending" && res.items.length > 0 && (
        <p className="text-sm text-muted">Still in their hold period, or held for review. You can still mark them paid if you paid early; a refund after that is netted from the next payout.</p>
      )}
      <Card>
        {res.items.length === 0 ? <Empty>{active.empty}</Empty> : <CommissionTable rows={res.items} withCustomer pickForm={pickable ? form : undefined} />}
      </Card>
      <Pager path={path} params={{ tab: active.key === "due" ? undefined : active.key }} page={res.page} total={res.total} pageSize={res.page_size} />
      {pickable && (
        <ActionForm action={payCommissions} id={form} className="space-y-3 rounded-xl border border-line p-4">
          {/* Keyed on the rows, so the count resets once ticked ones are paid and leave the list. */}
          <PickedTotal key={res.items.map((c) => c.id).join()} form={form} />
          <div className="flex flex-wrap items-end gap-3">
            <label className="block min-w-56 flex-1">
              <span className="text-sm font-medium">Reference (optional)</span>
              <input className="input mt-1" name="reference" maxLength={200} placeholder="PayPal batch ID, Wise transfer, Paid in Rewardful" />
            </label>
            <Submit>Mark picked as paid</Submit>
          </div>
          <p className="text-xs text-muted">This records a payment you made yourself; Kickrail sends no money. The affiliate sees it as paid in their portal, and you can undo it from Payouts history.</p>
        </ActionForm>
      )}
    </section>
  );
}
