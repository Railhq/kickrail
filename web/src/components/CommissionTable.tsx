import Link from "next/link";
import { DeleteButton } from "@/components/DeleteButton";
import { Badge, StatusBadge, Table } from "@/components/ui";
import { date, money, relative } from "@/lib/format";
import type { Commission } from "@/lib/types";

// Stripe ids run to 60+ characters; show the start and keep the full id on hover.
const stripeId = (id: string) => <span className="block max-w-44 truncate font-mono text-xs" title={id}>{id}</span>;

function source(key: string) {
  if (key.startsWith("inv:")) return stripeId(key.slice(4));
  if (key.startsWith("cs:")) return stripeId(key.slice(3));
  if (key.startsWith("rw:")) return <span className="text-xs">Rewardful</span>;
  if (key.startsWith("clawback:")) return <span className="text-xs">refund after payout</span>;
  return key;
}

/** Commissions as a ledger. On a referral's own page the customer column is left out, since it's always that customer. */
export function CommissionTable({ rows, withCustomer = true }: { rows: Commission[]; withCustomer?: boolean }) {
  return (
    <Table head={[withCustomer ? "Affiliate / customer" : "Affiliate", "Amount", "On payment", "Status", "Payable", "Source", ""]}>
      {rows.map((c) => (
        <tr key={c.id} className="align-top">
          <td className="px-5 py-3">
            <Link href={`/dashboard/affiliates/${c.affiliate_id}`} className="hover:underline">{c.affiliate_name}</Link>
            {withCustomer && c.referral_id && (
              <p className="max-w-56 truncate text-xs text-muted">
                <Link href={`/dashboard/referrals/${c.referral_id}`} className="hover:underline">{c.customer ?? "view referral"}</Link>
              </p>
            )}
          </td>
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
  );
}
