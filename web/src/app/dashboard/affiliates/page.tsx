import Link from "next/link";
import { addAffiliate, setAffiliateStatus, updateAffiliate } from "@/app/actions";
import { ActionForm, Submit } from "@/components/ActionForm";
import { Badge, Card, Empty, Field, StatusBadge, Table } from "@/components/ui";
import { api } from "@/lib/backend";
import { date, money } from "@/lib/format";
import type { Affiliate, Campaign } from "@/lib/types";

export const metadata = { title: "Affiliates" };

/** Currencies this affiliate earned in, US dollars first, then largest. Each gets its own line; they can't be added up. */
const currencies = (m: Record<string, number>) =>
  Object.keys(m)
    .filter((c) => m[c] !== 0)
    .sort((x, y) => (x === "usd" ? -1 : y === "usd" ? 1 : m[y] - m[x]));

export default async function AffiliatesPage() {
  const [affs, campaigns] = await Promise.all([api<Affiliate[]>("/merchant/affiliates"), api<Campaign[]>("/merchant/campaigns")]);
  const campaignName = Object.fromEntries(campaigns.map((c) => [c.id, c.name]));
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
      <Card>
        {affs.length === 0 ? (
          <Empty>No affiliates yet. Share your program page from the Overview.</Empty>
        ) : (
          <Table compact head={["Affiliate", "Status", "Link / code", "Clicks", "Signups", "Customers", "Earned", ""]}>
            {affs.map((a) => (
              <tr key={a.id} className="align-top">
                <td className="px-3 py-3 first:pl-5 last:pr-5">
                  <Link href={`/dashboard/affiliates/${a.id}`} className="font-medium hover:underline">{a.name || a.email}</Link>
                  <p className="text-xs text-muted">{a.email}</p>
                  <p className="mt-1 text-xs text-muted">Joined {date(a.created_at)} · {campaignName[a.campaign_id]}</p>
                  {a.rate_override_description && <p className="mt-1 text-xs text-amber-800">Custom rate: {a.rate_override_description}</p>}
                </td>
                <td className="px-3 py-3 first:pl-5 last:pr-5">
                  <StatusBadge status={a.status} />
                  {!a.can_be_paid && a.status === "approved" && <p className="mt-1 text-xs text-muted">no payout details yet</p>}
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
                <td className="px-3 py-3 first:pl-5 last:pr-5 num">{a.clicks}</td>
                <td className="px-3 py-3 first:pl-5 last:pr-5 num">{a.leads}</td>
                <td className="px-3 py-3 first:pl-5 last:pr-5 num">{a.customers}</td>
                <td className="px-3 py-3 first:pl-5 last:pr-5 num">
                  {currencies(a.earned).length === 0 && money(0)}
                  {currencies(a.earned).map((cur) => (
                    <div key={cur} className="whitespace-nowrap [&+&]:mt-1.5">
                      {money(a.earned[cur], cur)}
                      <p className="text-xs text-muted">{money(a.paid[cur] ?? 0, cur)} paid</p>
                    </div>
                  ))}
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
    </div>
  );
}
