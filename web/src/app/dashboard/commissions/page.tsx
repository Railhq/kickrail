import Link from "next/link";
import { CommissionTable } from "@/components/CommissionTable";
import { listHref, Pager, SearchBox } from "@/components/ListControls";
import { Card, Empty } from "@/components/ui";
import { api } from "@/lib/backend";
import type { Commission, Page } from "@/lib/types";

export const metadata = { title: "Commissions" };

const PATH = "/dashboard/commissions";
const STATUSES: [string, string][] = [["", "All"], ["pending", "Unpaid"], ["paid", "Paid"], ["void", "Void"]];

export default async function CommissionsPage({ searchParams }: { searchParams: Promise<{ status?: string; q?: string; page?: string }> }) {
  const sp = await searchParams;
  const status = STATUSES.some(([v]) => v && v === sp.status) ? sp.status : undefined;
  const page = Math.max(1, Number.parseInt(sp.page ?? "1", 10) || 1);
  const q = sp.q?.trim() || undefined;
  const qs = new URLSearchParams({ page: String(page) });
  if (status) qs.set("status", status);
  if (q) qs.set("q", q);
  const res = await api<Page<Commission>>(`/merchant/commissions?${qs}`);
  const params = { status, q };
  return (
    <div className="space-y-6">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <h1 className="page-title">Commissions</h1>
        <a className="btn btn-secondary" href="/api/merchant/export/commissions.csv" download>Export CSV</a>
      </div>
      <p className="text-sm text-muted">Refunds and disputes shrink or void unpaid commissions automatically. If the commission was already paid, a negative line is netted from that affiliate&apos;s next payout. You can delete an unpaid commission that isn&apos;t in a payout; every delete is recorded in the audit log.</p>
      <div className="flex flex-wrap items-center justify-between gap-3">
        <SearchBox path={PATH} params={params} placeholder="Customer email, affiliate or Stripe invoice" />
        <div className="flex flex-wrap gap-1 text-sm">
          {STATUSES.map(([value, label]) => (
            <Link key={label} href={listHref(PATH, { status: value, q })} className={`btn ${(status ?? "") === value ? "btn-primary" : "btn-secondary"}`}>{label}</Link>
          ))}
        </div>
      </div>
      <Card>
        {res.items.length === 0 ? (
          <Empty>{q ? `Nothing matches “${q}”.` : status ? "No commissions here." : "No commissions yet. They are created when a referred customer pays."}</Empty>
        ) : (
          <CommissionTable rows={res.items} />
        )}
      </Card>
      <Pager path={PATH} params={params} page={res.page} total={res.total} pageSize={res.page_size} />
    </div>
  );
}
