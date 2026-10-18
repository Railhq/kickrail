import Link from "next/link";
import { Card, Empty, Notice, StatusBadge } from "@/components/ui";
import { api } from "@/lib/backend";
import { moneyMap } from "@/lib/format";

type Totals = Record<string, { in_hold: number; payable: number; paid: number }>;
type Portal = { user: { name: string; payouts_enabled: boolean; can_be_paid: boolean }; programs: { affiliate_id: string; status: string; program: { slug: string; name: string }; clicks: number; customers: number; totals: Totals }[] };

export const metadata = { title: "Your programs" };

const sum = (t: Totals, k: "in_hold" | "payable" | "paid") => Object.fromEntries(Object.entries(t).map(([c, v]) => [c, v[k]]));

export default async function PortalHome() {
  const p = await api<Portal>("/portal");
  return (
    <div className="space-y-6">
      <h1 className="page-title">Your programs</h1>
      {!p.user.can_be_paid && p.programs.length > 0 && (
        <Notice>Tell programs where to send your money, so they can pay what you earn. <Link className="link" href="/a/payouts">Add payout details →</Link></Notice>
      )}
      {p.programs.length === 0 ? (
        <Card><Empty>You haven&apos;t joined any programs yet. Open a program&apos;s join link to get started.</Empty></Card>
      ) : (
        <div className="grid gap-4 sm:grid-cols-2">
          {p.programs.map((x) => (
            <Link key={x.affiliate_id} href={`/a/${x.affiliate_id}`} className="card block transition hover:border-stone-300">
              <div className="flex items-center justify-between">
                <h2 className="font-semibold">{x.program.name}</h2>
                <StatusBadge status={x.status} />
              </div>
              <dl className="mt-4 grid grid-cols-3 gap-2 text-sm">
                <div><dt className="text-xs text-muted">In hold</dt><dd className="num">{moneyMap(sum(x.totals, "in_hold"))}</dd></div>
                <div><dt className="text-xs text-muted">Payable</dt><dd className="num">{moneyMap(sum(x.totals, "payable"))}</dd></div>
                <div><dt className="text-xs text-muted">Paid</dt><dd className="num">{moneyMap(sum(x.totals, "paid"))}</dd></div>
              </dl>
              <p className="mt-3 text-xs text-muted">{x.clicks} clicks · {x.customers} customers</p>
            </Link>
          ))}
        </div>
      )}
    </div>
  );
}
