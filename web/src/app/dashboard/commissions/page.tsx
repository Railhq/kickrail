import { DeleteButton } from "@/components/DeleteButton";
import { Badge, Card, Empty, StatusBadge, Table } from "@/components/ui";
import { api } from "@/lib/backend";
import { date, money, relative } from "@/lib/format";
import type { Commission } from "@/lib/types";

export const metadata = { title: "Commissions" };

function source(key: string) {
  if (key.startsWith("inv:")) return <span className="font-mono text-xs">{key.slice(4)}</span>;
  if (key.startsWith("cs:")) return <span className="font-mono text-xs">{key.slice(3)}</span>;
  if (key.startsWith("clawback:")) return <span className="text-xs">refund after payout</span>;
  return key;
}

export default async function CommissionsPage() {
  const rows = await api<Commission[]>("/merchant/commissions");
  return (
    <div className="space-y-6">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <h1 className="page-title">Commissions</h1>
        <a className="btn btn-secondary" href="/api/merchant/export/commissions.csv" download>Export CSV</a>
      </div>
      <p className="text-sm text-muted">Refunds and disputes shrink or void unpaid commissions automatically. If the commission was already paid, a negative line is netted from that affiliate&apos;s next payout. You can delete an unpaid commission that isn&apos;t in a payout; every delete is recorded in the audit log.</p>
      <Card>
        {rows.length === 0 ? (
          <Empty>No commissions yet. They are created when a referred customer pays.</Empty>
        ) : (
          <Table head={["Affiliate", "Amount", "On payment", "Status", "Payable", "Source", ""]}>
            {rows.map((c) => (
              <tr key={c.id}>
                <td className="px-5 py-3">{c.affiliate_name}</td>
                <td className={`px-5 py-3 num ${c.amount_cents < 0 ? "text-red-700" : ""}`}>{money(c.amount_cents, c.currency)}</td>
                <td className="px-5 py-3 num text-muted">{c.base_cents > 0 ? money(c.base_cents, c.currency) : ""}</td>
                <td className="px-5 py-3">
                  <StatusBadge status={c.status} />
                  {c.held && c.status === "pending" && <span className="ml-1"><Badge tone="amber">held for review</Badge></span>}
                  {c.payout_id && c.status === "pending" && <span className="ml-1"><Badge tone="blue">in payout</Badge></span>}
                  {c.void_reason && <p className="mt-1 text-xs text-muted">{c.void_reason}</p>}
                </td>
                <td className="px-5 py-3 text-muted">{c.status === "pending" ? (new Date(c.due_at) > new Date() ? relative(c.due_at) : "now") : c.status === "paid" ? "paid" : ""}</td>
                <td className="px-5 py-3 text-muted">{source(c.source_key)}<p className="text-xs">{date(c.created_at)}</p></td>
                <td className="px-5 py-3 text-right">
                  {c.status !== "paid" && !c.payout_id && <DeleteButton kind="commissions" id={c.id} confirmText={`Delete this ${money(c.amount_cents, c.currency)} commission for ${c.affiliate_name}? It's kept in your audit log, and the same payment won't earn it again. Add a reason (optional):`} />}
                </td>
              </tr>
            ))}
          </Table>
        )}
      </Card>
    </div>
  );
}
