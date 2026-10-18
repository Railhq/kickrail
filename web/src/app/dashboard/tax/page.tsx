import Link from "next/link";
import { Badge, Card, Empty, Notice, Table } from "@/components/ui";
import { api } from "@/lib/backend";
import { date, moneyMap } from "@/lib/format";
import { getMe } from "@/lib/me";
import type { Merchant } from "@/lib/types";

export const metadata = { title: "Tax forms" };

type Row = { affiliate_id: string; name: string; email: string; form: string | null; legal_name: string | null; country: string | null; tin_last4: string | null; signed_at: string | null; paid_this_year: Record<string, number> };

const FORM = { w9: "W-9", w8ben: "W-8BEN", w8bene: "W-8BEN-E" } as Record<string, string>;

export default async function TaxPage() {
  const [t, m, me] = await Promise.all([api<{ year: number; require_tax_form: boolean; affiliates: Row[] }>("/merchant/tax"), api<Merchant>("/merchant"), getMe("/dashboard/tax")]);
  const owner = me.user.id === m.owner_id;
  const missing = t.affiliates.filter((a) => !a.form).length;
  return (
    <div className="space-y-6">
      <h1 className="page-title">Tax forms</h1>
      <p className="text-sm text-muted">
        Affiliates sign a W-9 (US persons) or W-8BEN / W-8BEN-E (everyone else) in their portal. Tax IDs are encrypted; only the last four digits show here.
      </p>
      {!t.require_tax_form && (
        <Notice>
          Forms are optional right now, so affiliates without one can still be paid. Turn on <b>Require a signed W-9 or W-8</b> in <Link className="link" href="/dashboard/settings">Settings</Link> to hold their payouts until they sign.
        </Notice>
      )}
      <Card
        title={`${t.affiliates.length - missing} of ${t.affiliates.length} on file`}
        actions={
          owner ? (
            <a className="btn btn-secondary" href={`/api/merchant/tax/1099.csv?year=${t.year}`} title="US affiliates paid 600 USD or more, with full TINs">1099-NEC list {t.year}</a>
          ) : (
            <span className="text-xs text-muted">Only the workspace owner can download TINs</span>
          )
        }
      >
        {t.affiliates.length === 0 ? (
          <Empty>No affiliates yet.</Empty>
        ) : (
          <Table head={["Affiliate", "Form", "Legal name", "TIN", "Signed", `Paid in ${t.year}`]}>
            {t.affiliates.map((a) => (
              <tr key={a.affiliate_id}>
                <td className="px-5 py-3"><p className="font-medium">{a.name}</p><p className="text-xs text-muted">{a.email}</p></td>
                <td className="px-5 py-3">{a.form ? <Badge tone="green">{FORM[a.form]}</Badge> : <Badge tone="amber">missing</Badge>}</td>
                <td className="px-5 py-3">{a.legal_name}{a.country && <span className="ml-1 text-xs text-muted">{a.country}</span>}</td>
                <td className="px-5 py-3 font-mono text-xs">{a.tin_last4 && `•••${a.tin_last4}`}</td>
                <td className="px-5 py-3 text-muted">{date(a.signed_at)}</td>
                <td className="num px-5 py-3">{moneyMap(a.paid_this_year)}</td>
              </tr>
            ))}
          </Table>
        )}
      </Card>
    </div>
  );
}
