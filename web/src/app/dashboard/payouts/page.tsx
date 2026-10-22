import Link from "next/link";
import { cancelPayout, createPayout, syncPayout, undoPayout } from "@/app/actions";
import { ActionForm, Submit } from "@/components/ActionForm";
import { Badge, Card, Empty, StatusBadge, Table } from "@/components/ui";
import { api } from "@/lib/backend";
import { date, money, moneyMap, relative } from "@/lib/format";
import type { PayableLine, Payout, PayoutDetails, UpcomingLine } from "@/lib/types";

const METHOD_LABEL: Record<PayoutDetails["method"], string> = { paypal: "PayPal", wise: "Wise", bank: "Bank", other: "Other" };

export const metadata = { title: "Payouts" };

export default async function PayoutsPage({ searchParams }: { searchParams: Promise<{ funded?: string; cancelled?: string }> }) {
  const sp = await searchParams;
  const { payable, upcoming, history, fee_bps, paypal_connected, stripe_payouts } = await api<{ payable: PayableLine[]; upcoming: UpcomingLine[]; history: Payout[]; fee_bps: number; paypal_connected: boolean; stripe_payouts: boolean }>("/merchant/payouts");
  const currencies = [...new Set(payable.map((l) => l.currency))];
  return (
    <div className="space-y-6">
      <h1 className="page-title">Payouts</h1>
      {sp.funded && <p className="rounded-xl border border-emerald-200 bg-emerald-50 p-3 text-sm text-emerald-900">Payment received. Transfers go out as soon as Stripe confirms it, usually within a minute.</p>}
      {sp.cancelled && <p className="rounded-xl border border-line bg-sunk/50 p-3 text-sm">Checkout was cancelled. The payout is still waiting for funding; cancel it below to release its commissions.</p>}

      {currencies.length === 0 ? (
        <Card title="Ready to pay"><Empty>Nothing is payable yet. Commissions become payable after their hold period, once an affiliate passes the minimum payout.</Empty></Card>
      ) : (
        currencies.map((cur) => {
          const lines = payable.filter((l) => l.currency === cur);
          const viaStripe = stripe_payouts ? lines.filter((l) => l.payouts_enabled && !l.needs_tax_form) : [];
          const viaPayPal = lines.filter((l) => l.paypal_email && !l.needs_tax_form);
          const total = (ls: PayableLine[]) => ls.reduce((s, l) => s + l.amount_cents, 0);
          return (
            <Card
              key={cur}
              title={`Ready to pay · ${cur.toUpperCase()}`}
              actions={
                <div className="flex gap-2">
                  <a className="btn btn-secondary" href={`/api/merchant/payouts/due.csv?currency=${cur}`}>Download CSV</a>
                  {viaPayPal.length > 0 && <a className="btn btn-secondary" href={`/api/merchant/payouts/paypal.csv?currency=${cur}`} title="Upload to PayPal's own Payouts page">PayPal CSV</a>}
                </div>
              }
            >
              <p className="mb-4 text-sm text-muted">
                Pay each affiliate yourself using the details they saved, then tick who you paid and mark them paid. Their commissions move to paid and they see it in their portal.
              </p>
              <Table head={["", "Affiliate", "Amount", "Pay to", "Commissions"]}>
                {lines.map((l) => (
                  <tr key={l.affiliate_id}>
                    <td className="py-3 pl-5">
                      <input type="checkbox" name="affiliate_ids" value={l.affiliate_id} form={`manual-${cur}`} defaultChecked={!l.needs_tax_form} disabled={l.needs_tax_form} aria-label={`Paid ${l.name}`} />
                    </td>
                    <td className="px-5 py-3">
                      <p className="font-medium">{l.name}</p>
                      <p className="text-xs text-muted">{l.email}</p>
                      {l.needs_tax_form && <p className="mt-1"><Badge tone="amber">tax form missing</Badge></p>}
                    </td>
                    <td className="px-5 py-3 num">{money(l.amount_cents, cur)}</td>
                    <td className="px-5 py-3">
                      {l.payout_details ? (
                        <><p className="text-xs text-muted">{METHOD_LABEL[l.payout_details.method]}</p><p className="break-all font-mono text-xs">{l.payout_details.value}</p></>
                      ) : l.payouts_enabled ? (
                        <Badge tone="green">Stripe ready</Badge>
                      ) : (
                        <span className="text-xs text-amber-800">No details yet; email them</span>
                      )}
                    </td>
                    <td className="px-5 py-3 num">{l.commission_ids.length}</td>
                  </tr>
                ))}
              </Table>
              <ActionForm action={createPayout} id={`manual-${cur}`} className="mt-5 flex flex-wrap items-end gap-3">
                <input type="hidden" name="currency" value={cur} />
                <input type="hidden" name="method" value="manual" />
                <label className="block min-w-56 flex-1">
                  <span className="text-sm font-medium">Reference (optional)</span>
                  <input className="input mt-1" name="reference" maxLength={200} placeholder="PayPal batch ID, Wise transfer, note" />
                </label>
                <Submit>Mark ticked as paid</Submit>
              </ActionForm>
              {paypal_connected && viaPayPal.length > 0 && (
                <ActionForm action={createPayout} className="mt-4 border-t border-line pt-4">
                  <input type="hidden" name="currency" value={cur} />
                  <input type="hidden" name="method" value="paypal" />
                  {viaPayPal.map((l) => <input key={l.affiliate_id} type="hidden" name="affiliate_ids" value={l.affiliate_id} />)}
                  <p className="text-sm text-muted">
                    Or send {money(total(viaPayPal), cur)} to the {viaPayPal.length} with a PayPal email through your PayPal account, in one batch. Each one moves to paid when PayPal confirms it.
                  </p>
                  <Submit variant="secondary" className="mt-3">Send with PayPal</Submit>
                </ActionForm>
              )}
              {!paypal_connected && viaPayPal.length > 0 && (
                <p className="mt-4 border-t border-line pt-4 text-sm text-muted">
                  {viaPayPal.length} of these use PayPal. <Link className="link" href="/dashboard/settings">Connect PayPal</Link> to pay them in one batch.
                </p>
              )}
              {viaStripe.length > 0 && (
                <ActionForm action={createPayout} className="mt-4 border-t border-line pt-4">
                  <input type="hidden" name="currency" value={cur} />
                  <input type="hidden" name="method" value="stripe" />
                  <p className="text-sm text-muted">
                    Or pay the {viaStripe.length} with Stripe set up automatically: {money(total(viaStripe), cur)}
                    {fee_bps > 0 && ` + ${(fee_bps / 100).toFixed(2)}% fee`}, one card payment, then a Stripe transfer to each.
                  </p>
                  <Submit variant="secondary" className="mt-3">Fund Stripe payout</Submit>
                </ActionForm>
              )}
            </Card>
          );
        })
      )}

      {upcoming.length > 0 && (
        <Card title="Upcoming">
          <p className="mb-4 text-sm text-muted">Unpaid commissions that aren&apos;t ready yet. Paid an affiliate early? Open them and mark the commissions you paid.</p>
          <Table head={["Affiliate", "Unpaid", "Commissions", "Why not ready", ""]}>
            {upcoming.map((u) => {
              const why = [
                u.next_due_at && `Next due ${date(u.next_due_at)} (${relative(u.next_due_at)})`,
                u.under_minimum && "Some due, under the minimum payout",
                u.held > 0 && `${u.held} held for review`,
              ].filter(Boolean);
              return (
                <tr key={u.affiliate_id} className="align-top">
                  <td className="px-5 py-3">
                    <p className="font-medium">{u.name || u.email}</p>
                    {u.name && <p className="text-xs text-muted">{u.email}</p>}
                  </td>
                  <td className="px-5 py-3 num">{moneyMap(u.amounts)}</td>
                  <td className="px-5 py-3 num">{u.count}</td>
                  <td className="px-5 py-3 text-sm text-muted">{why.map((w) => <p key={String(w)}>{w}</p>)}</td>
                  <td className="px-5 py-3 text-right">
                    <Link className="btn btn-secondary whitespace-nowrap" href={`/dashboard/affiliates/${u.affiliate_id}${u.under_minimum ? "" : "?tab=pending"}#commissions`}>Pay early</Link>
                  </td>
                </tr>
              );
            })}
          </Table>
        </Card>
      )}

      <Card title="History">
        {history.length === 0 ? (
          <Empty>No payouts yet.</Empty>
        ) : (
          <Table head={["Created", "Method", "Status", "Affiliates", "Total", ""]}>
            {history.map((p) => (
              <tr key={p.id} className="align-top">
                <td className="px-5 py-3">{date(p.created_at)}</td>
                <td className="px-5 py-3">
                  {p.method === "stripe" ? "Stripe" : p.method === "paypal" ? "PayPal" : "Manual"}
                  {p.reference && <p className="text-xs text-muted">{p.reference}</p>}
                </td>
                <td className="px-5 py-3">
                  <StatusBadge status={p.status} />
                  {p.items.filter((i) => i.error).map((i) => <p key={i.affiliate_id} className="mt-1 text-xs text-red-700">{i.error}</p>)}
                  {p.method === "paypal" && p.status === "processing" && <p className="mt-1 text-xs text-muted">{p.items.filter((i) => i.status === "paid").length} of {p.items.length} confirmed</p>}
                </td>
                <td className="px-5 py-3 num">{p.items.length}</td>
                <td className="px-5 py-3 num">{money(p.total_cents, p.currency)}</td>
                <td className="px-5 py-3">
                  <div className="flex justify-end gap-2">
                    {p.method === "paypal" && p.status === "processing" && <form action={syncPayout.bind(null, p.id)}><button className="btn btn-secondary" title="Ask PayPal for the latest status">Refresh</button></form>}
                    {p.status === "awaiting_funding" && p.funding_url && <a className="btn btn-primary" href={p.funding_url}>Pay now</a>}
                    {p.status === "awaiting_funding" && <form action={cancelPayout.bind(null, p.id)}><button className="btn btn-danger">Cancel</button></form>}
                    {p.method === "manual" && p.status === "paid" && <form action={undoPayout.bind(null, p.id)}><button className="btn btn-secondary" title="Recorded by mistake? Moves these commissions back to Ready to pay.">Undo</button></form>}
                    <a className="btn btn-secondary" href={`/api/merchant/payouts/${p.id}/csv`}>CSV</a>
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
