import Link from "next/link";
import { addAffiliate, setAffiliateStatus, updateAffiliate } from "@/app/actions";
import { ActionForm, Submit } from "@/components/ActionForm";
import { listHref, Pager, SearchBox } from "@/components/ListControls";
import { Badge, Card, Empty, Field, StatusBadge, Table } from "@/components/ui";
import { api } from "@/lib/backend";
import { date, displayMoney, type Fx, fxNote } from "@/lib/format";
import type { Affiliate, Campaign, Page } from "@/lib/types";

export const metadata = { title: "Affiliates" };

const PATH = "/dashboard/affiliates";

export default async function AffiliatesPage({ searchParams }: { searchParams: Promise<{ campaign?: string; q?: string; page?: string }> }) {
  const sp = await searchParams;
  const page = Math.max(1, Number.parseInt(sp.page ?? "1", 10) || 1);
  const q = sp.q?.trim() || undefined;
  const campaign = sp.campaign || undefined;
  const qs = new URLSearchParams({ page: String(page) });
  if (campaign) qs.set("campaign_id", campaign);
  if (q) qs.set("q", q);
  const [res, campaigns, fx] = await Promise.all([
    api<Page<Affiliate> & { by_campaign: Record<string, number> }>(`/merchant/affiliates?${qs}`),
    api<Campaign[]>("/merchant/campaigns"),
    api<Fx>("/merchant/fx"),
  ]);
  const affs = res.items;
  const mixed = affs.some((a) => Object.values(a.earned).filter(Boolean).length > 1 || displayMoney(a.earned, fx).rest);
  const linkParams = { campaign, q };
  const everyone = Object.values(res.by_campaign).reduce((n, x) => n + x, 0);
  // Campaigns that hand out rewards instead of cash: no money columns, no payout details needed.
  const customReward = new Set(campaigns.filter((c) => c.reward?.type === "custom").map((c) => c.id));
  return (
    <div className="space-y-6">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <h1 className="page-title">Affiliates</h1>
        <div className="flex gap-2">
          <a className="btn btn-secondary" href="/api/merchant/export/affiliates.csv" download>Export CSV</a>
          <details className="group relative">
            <summary className="btn btn-primary cursor-pointer list-none">Add affiliate</summary>
            <Card className="absolute right-0 z-20 mt-2 w-[min(22rem,calc(100vw-2rem))] shadow-lg">
              <ActionForm action={addAffiliate} className="space-y-3">
                <Field label="Name"><input className="input" name="name" required maxLength={100} /></Field>
                <Field label="Email"><input className="input" name="email" type="email" required /></Field>
                <Field label="Campaign">
                  <select name="campaign_id" className="input" defaultValue={campaigns.find((c) => c.is_default)?.id}>
                    {campaigns.map((c) => <option key={c.id} value={c.id}>{c.name}</option>)}
                  </select>
                </Field>
                <label className="flex items-start gap-2 text-sm">
                  <input type="checkbox" name="send_welcome_email" defaultChecked className="mt-1" />
                  <span>Email them a welcome with their link and a set-password link</span>
                </label>
                <Submit className="w-full">Add and approve</Submit>
              </ActionForm>
            </Card>
          </details>
        </div>
      </div>
      <div className="flex flex-wrap items-center justify-between gap-3">
        <SearchBox path={PATH} params={linkParams} placeholder="Name, email or link" />
        {campaigns.length > 1 && (
          <div className="flex flex-wrap gap-1 text-sm" aria-label="Campaign">
            {[{ id: undefined, name: "All campaigns", n: everyone }, ...campaigns.map((c) => ({ id: c.id, name: c.name, n: res.by_campaign[c.id] ?? 0 }))].map((c) => (
              <Link key={c.id ?? "all"} href={listHref(PATH, { campaign: c.id, q })} className={`btn ${campaign === c.id ? "btn-primary" : "btn-secondary"}`}>
                {c.name} <span className="num ml-1 opacity-70">{c.n.toLocaleString()}</span>
              </Link>
            ))}
          </div>
        )}
      </div>
      <Card>
        {affs.length === 0 ? (
          <Empty>{q ? `Nothing matches “${q}”.` : campaign ? "No affiliates on this campaign yet." : "No affiliates yet. Share your program page from the Overview."}</Empty>
        ) : (
          <Table compact head={["Affiliate", "Campaign", "Status", "Link / code", "Referrals", "Earned", ""]}>
            {affs.map((a) => (
              <tr key={a.id} className="align-top">
                <td className="px-3 py-3 first:pl-5 last:pr-5">
                  <Link href={`/dashboard/affiliates/${a.id}`} className="font-medium hover:underline">{a.name || a.email}</Link>
                  <p className="text-xs text-muted">{a.email}</p>
                  <p className="mt-1 text-xs text-muted">Joined {date(a.created_at)}</p>
                  {a.rate_override_description && <p className="mt-1 text-xs text-amber-800">Custom rate: {a.rate_override_description}</p>}
                </td>
                <td className="px-3 py-3 first:pl-5 last:pr-5">
                  <Link href={listHref(PATH, { campaign: a.campaign_id })} className="hover:underline">{a.campaign_name}</Link>
                </td>
                <td className="px-3 py-3 first:pl-5 last:pr-5">
                  <StatusBadge status={a.status} />
                  {!a.can_be_paid && a.status === "approved" && !customReward.has(a.campaign_id) && <p className="mt-1 text-xs text-muted">no payout details yet</p>}
                  {a.tax_form && <p className="mt-1 text-xs text-muted">{a.tax_form === "w9" ? "W-9" : a.tax_form === "w8ben" ? "W-8BEN" : "W-8BEN-E"} on file</p>}
                </td>
                <td className="px-3 py-3 first:pl-5 last:pr-5">
                  <p className="whitespace-nowrap font-mono text-xs">?{new URL(a.link).search.slice(1)}</p>
                  {a.code && (
                    <p className="mt-1">
                      <Badge tone={a.stripe_promotion_code === a.code ? "green" : "gray"}>{a.code}</Badge>
                      {a.stripe_promotion_code === a.code && <span className="ml-1 text-xs text-muted">redeemable</span>}
                    </p>
                  )}
                  {a.links.length + a.codes.length > 0 && (
                    <p className="mt-1 text-xs text-muted">
                      +{a.links.length} link{a.links.length === 1 ? "" : "s"}, {a.codes.length} code{a.codes.length === 1 ? "" : "s"}
                    </p>
                  )}
                </td>
                <td className="whitespace-nowrap px-3 py-3 text-xs text-muted first:pl-5 last:pr-5">
                  <p><span className="num text-sm text-fg">{a.customers.toLocaleString()}</span> customers</p>
                  <p className="mt-1"><span className="num">{a.leads.toLocaleString()}</span> signups</p>
                  <p><span className="num">{a.clicks.toLocaleString()}</span> clicks</p>
                </td>
                <td className="px-3 py-3 first:pl-5 last:pr-5 num">
                  {customReward.has(a.campaign_id) ? (
                    <span className="text-xs text-muted">rewards, not cash</span>
                  ) : (() => {
                    const [earned, paid] = [displayMoney(a.earned, fx), displayMoney(a.paid, fx)];
                    return (
                      <div className="whitespace-nowrap">
                        {earned.main}
                        {earned.rest && <p className="text-xs text-muted">{earned.rest}</p>}
                        <p className="mt-1 text-xs text-muted">{paid.main} paid</p>
                      </div>
                    );
                  })()}
                </td>
                <td className="px-3 py-3 first:pl-5 last:pr-5">
                  <div className="flex w-24 flex-col items-stretch gap-1.5">
                    <Link href={`/dashboard/affiliates/${a.id}`} className="btn btn-secondary btn-sm whitespace-nowrap">View as</Link>
                    {a.status !== "approved" && (
                      <form action={setAffiliateStatus.bind(null, a.id, "approved")}><button className="btn btn-primary btn-sm w-full">Approve</button></form>
                    )}
                    {a.status !== "rejected" && (
                      <form action={setAffiliateStatus.bind(null, a.id, "rejected")}><button className="btn btn-danger btn-sm w-full">{a.status === "pending" ? "Decline" : "Remove"}</button></form>
                    )}
                    <details className="relative text-center">
                      <summary className="cursor-pointer text-xs text-muted">Edit</summary>
                      <ActionForm action={updateAffiliate} className="absolute right-0 z-20 mt-2 w-56 space-y-2 rounded-xl border border-line bg-surface p-3 text-left shadow-lg">
                        <input type="hidden" name="id" value={a.id} />
                        <select name="campaign_id" defaultValue={a.campaign_id} className="input">
                          {campaigns.map((c) => <option key={c.id} value={c.id}>{c.name}</option>)}
                        </select>
                        <input name="code" defaultValue={a.code} placeholder="Creator code" className="input font-mono uppercase" pattern="[A-Za-z0-9]{3,20}" />
                        <Submit variant="secondary" className="w-full">Save</Submit>
                      </ActionForm>
                    </details>
                  </div>
                </td>
              </tr>
            ))}
          </Table>
        )}
      </Card>
      <Pager path={PATH} params={linkParams} page={res.page} total={res.total} pageSize={res.page_size} />
      {mixed && <p className="text-xs text-muted">{fxNote(fx)}</p>}
    </div>
  );
}
