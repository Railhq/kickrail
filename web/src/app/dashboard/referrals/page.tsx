import Link from "next/link";
import { reviewReferral } from "@/app/actions";
import { listHref, Pager, SearchBox } from "@/components/ListControls";
import { Badge, Card, Empty, StatusBadge, Table } from "@/components/ui";
import { api } from "@/lib/backend";
import { date, referralSource, referralWho } from "@/lib/format";
import type { Page, Referral } from "@/lib/types";

export const metadata = { title: "Referrals" };

const PATH = "/dashboard/referrals";

export default async function ReferralsPage({ searchParams }: { searchParams: Promise<{ flagged?: string; status?: string; q?: string; page?: string }> }) {
  const sp = await searchParams;
  const flagged = sp.flagged === "1";
  const status = sp.status === "lead" || sp.status === "customer" ? sp.status : undefined;
  const page = Math.max(1, Number.parseInt(sp.page ?? "1", 10) || 1);
  const q = sp.q?.trim() || undefined;
  // One filter at a time: "Needs review" is its own tab.
  const view = flagged ? "review" : (status ?? "");
  const qs = new URLSearchParams({ page: String(page) });
  if (flagged) qs.set("flagged", "true");
  if (status) qs.set("status", status);
  if (q) qs.set("q", q);
  const res = await api<Page<Referral>>(`/merchant/referrals?${qs}`);
  const linkParams = { flagged: flagged ? "1" : undefined, status, q };
  return (
    <div className="space-y-6">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <h1 className="page-title">Referrals</h1>
        <a className="btn btn-secondary" href="/api/merchant/export/referrals.csv" download>Export CSV</a>
      </div>
      <div className="flex flex-wrap items-center justify-between gap-3">
        <SearchBox path={PATH} params={linkParams} placeholder="Email, Stripe customer, user id or affiliate" />
        <ViewTabs current={view} q={q} />
      </div>
      {flagged && <p className="text-sm text-muted">These referrals matched the affiliate on email, company domain or sign-in IP. Their commissions are held until you approve them. Rejecting voids unpaid commissions.</p>}
      <Card>
        {res.items.length === 0 ? (
          <Empty>{q ? `Nothing matches “${q}”.` : flagged ? "Nothing to review." : "No referrals yet. They appear when a referred visitor signs up or pays."}</Empty>
        ) : (
          <Table head={["Customer", "Affiliate", "Status", "Source", "Signed up", ""]}>
            {res.items.map((r) => {
              const open = r.flags.length > 0 && !r.flags_cleared;
              return (
                <tr key={r.id} className="align-top hover:bg-sunk/40">
                  <td className="px-5 py-3">
                    <Link href={`${PATH}/${r.id}`} className="font-medium hover:underline">{referralWho(r)}</Link>
                    {r.stripe_customer_id && <p className="font-mono text-xs text-muted">{r.stripe_customer_id}</p>}
                    {r.flags.length > 0 && (
                      <ul className="mt-1 space-y-0.5">
                        {r.flags.map((f) => <li key={f.kind} className={`text-xs ${open ? "text-amber-800" : "text-muted"}`}>⚑ {f.detail}</li>)}
                      </ul>
                    )}
                  </td>
                  <td className="px-5 py-3"><Link href={`/dashboard/affiliates/${r.affiliate_id}`} className="hover:underline">{r.affiliate_name}</Link></td>
                  <td className="px-5 py-3">
                    <StatusBadge status={r.status} />
                    {open && <span className="ml-1"><Badge tone="amber">held</Badge></span>}
                    {r.rejected && <span className="ml-1"><Badge tone="red">rejected</Badge></span>}
                    {r.test && <span className="ml-1" title="Came through a test link, so it isn't counted and earns nothing"><Badge>test</Badge></span>}
                  </td>
                  <td className="px-5 py-3 text-muted">{referralSource(r.source)}</td>
                  <td className="px-5 py-3 text-muted">{date(r.created_at)}</td>
                  <td className="px-5 py-3">
                    <div className="flex justify-end gap-2">
                      {open && <form action={reviewReferral.bind(null, r.id, "clear")}><button className="btn btn-primary">Approve</button></form>}
                      {open && <form action={reviewReferral.bind(null, r.id, "reject")}><button className="btn btn-danger">Reject</button></form>}
                      <Link href={`${PATH}/${r.id}`} className="btn btn-secondary">View</Link>
                    </div>
                  </td>
                </tr>
              );
            })}
          </Table>
        )}
      </Card>
      <Pager path={PATH} params={linkParams} page={res.page} total={res.total} pageSize={res.page_size} />
    </div>
  );
}

function ViewTabs({ current, q }: { current: string; q?: string }) {
  const options: [string, string, Record<string, string | undefined>][] = [
    ["", "All", {}],
    ["customer", "Customers", { status: "customer" }],
    ["lead", "Leads", { status: "lead" }],
    ["review", "Needs review", { flagged: "1" }],
  ];
  return (
    <div className="flex flex-wrap gap-1 text-sm">
      {options.map(([value, label, p]) => (
        <Link key={value} href={listHref(PATH, { ...p, q })} className={`btn ${current === value ? "btn-primary" : "btn-secondary"}`}>
          {label}
        </Link>
      ))}
    </div>
  );
}
