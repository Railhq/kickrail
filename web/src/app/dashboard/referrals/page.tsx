import Link from "next/link";
import { reviewReferral } from "@/app/actions";
import { Badge, Card, Empty, StatusBadge, Table } from "@/components/ui";
import { api } from "@/lib/backend";
import { date } from "@/lib/format";
import type { Referral } from "@/lib/types";

export const metadata = { title: "Referrals" };

const SOURCE: Record<string, string> = { link: "referral link", code: "creator code" };

export default async function ReferralsPage({ searchParams }: { searchParams: Promise<{ flagged?: string }> }) {
  const flagged = (await searchParams).flagged === "1";
  const refs = await api<Referral[]>(`/merchant/referrals${flagged ? "?flagged=true" : ""}`);
  return (
    <div className="space-y-6">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <h1 className="page-title">Referrals</h1>
        <div className="flex gap-1 text-sm">
          <Link href="/dashboard/referrals" className={`btn ${flagged ? "btn-secondary" : "btn-primary"}`}>All</Link>
          <Link href="/dashboard/referrals?flagged=1" className={`btn ${flagged ? "btn-primary" : "btn-secondary"}`}>Needs review</Link>
          <a className="btn btn-secondary ml-1" href="/api/merchant/export/referrals.csv" download>Export CSV</a>
        </div>
      </div>
      {flagged && <p className="text-sm text-muted">These referrals matched the affiliate on email, company domain or sign-in IP. Their commissions are held until you approve them. Rejecting voids unpaid commissions.</p>}
      <Card>
        {refs.length === 0 ? (
          <Empty>{flagged ? "Nothing to review." : "No referrals yet. They appear when a referred visitor signs up or pays."}</Empty>
        ) : (
          <Table head={["Customer", "Affiliate", "Status", "Source", "Created", ""]}>
            {refs.map((r) => {
              const open = r.flags.length > 0 && !r.flags_cleared;
              return (
                <tr key={r.id} className="align-top">
                  <td className="px-5 py-3">
                    <p className="font-medium">{r.email ?? r.external_user_id ?? r.stripe_customer_id ?? "unknown"}</p>
                    {r.stripe_customer_id && <p className="font-mono text-xs text-muted">{r.stripe_customer_id}</p>}
                    {r.flags.length > 0 && (
                      <ul className="mt-1 space-y-0.5">
                        {r.flags.map((f) => <li key={f.kind} className={`text-xs ${open ? "text-amber-800" : "text-muted"}`}>⚑ {f.detail}</li>)}
                      </ul>
                    )}
                  </td>
                  <td className="px-5 py-3">{r.affiliate_name}</td>
                  <td className="px-5 py-3">
                    <StatusBadge status={r.status} />
                    {open && <span className="ml-1"><Badge tone="amber">held</Badge></span>}
                    {r.rejected && <span className="ml-1"><Badge tone="red">rejected</Badge></span>}
                  </td>
                  <td className="px-5 py-3 text-muted">{SOURCE[r.source] ?? r.source}</td>
                  <td className="px-5 py-3 text-muted">{date(r.created_at)}</td>
                  <td className="px-5 py-3">
                    {open && (
                      <div className="flex justify-end gap-2">
                        <form action={reviewReferral.bind(null, r.id, "clear")}><button className="btn btn-primary">Approve</button></form>
                        <form action={reviewReferral.bind(null, r.id, "reject")}><button className="btn btn-danger">Reject</button></form>
                      </div>
                    )}
                  </td>
                </tr>
              );
            })}
          </Table>
        )}
      </Card>
    </div>
  );
}
