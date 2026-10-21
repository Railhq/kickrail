import Link from "next/link";
import { addOwnLink, changeToken, deleteOwnLink } from "@/app/actions";
import { ActionForm, Submit } from "@/components/ActionForm";
import { CopyButton } from "@/components/CopyButton";
import { Badge, Card, Empty, Notice, Stat, StatGroup, StatusBadge, Table } from "@/components/ui";
import { date, mainCurrency, money, relative, splitMoney } from "@/lib/format";
import type { PortalView as View } from "@/lib/types";

/**
 * One program as its affiliate sees it. The merchant's "view as" renders the same
 * component with preview set, which swaps the affiliate's own controls for read-only text.
 */
export function PortalView({ d, preview = false, back }: { d: View; preview?: boolean; back?: React.ReactNode }) {
  const pick = (k: "in_hold" | "payable" | "paid") => Object.fromEntries(Object.entries(d.totals).map(([c, v]) => [c, v[k]]));
  const cur = mainCurrency(pick("in_hold"), pick("payable"), pick("paid"));
  const bal = { in_hold: splitMoney(pick("in_hold"), cur), payable: splitMoney(pick("payable"), cur), paid: splitMoney(pick("paid"), cur) };
  const nextRelease = d.commissions.filter((c) => c.status === "pending" && !c.held_for_review && new Date(c.due_at) > new Date()).map((c) => c.due_at).sort()[0];
  const b = d.program.branding ?? {};
  const accent = b.color ?? undefined;

  return (
    <div className="space-y-6">
      <div>
        {back}
        <div className="mt-3 flex flex-wrap items-center gap-3">
          {b.logo_url && (
            // eslint-disable-next-line @next/next/no-img-element
            <img src={b.logo_url} alt="" className="h-9 w-9 rounded-lg border border-line bg-surface object-contain p-1" />
          )}
          <h1 className="page-title">{d.program.name}</h1>
          <StatusBadge status={d.status} />
        </div>
        {d.program.terms && <p className="mt-2 text-sm text-muted">You earn {d.program.terms}.</p>}
        {b.terms_url && <a href={b.terms_url} target="_blank" rel="noopener" className="mt-1 inline-block text-xs text-muted underline">Program terms ↗</a>}
      </div>

      {d.status === "pending" && <Notice>Your application is waiting for approval. You can already test your link below; real clicks are tracked once you&apos;re approved.</Notice>}
      {d.status === "rejected" && <Notice>This program isn&apos;t accepting your referrals.</Notice>}
      {d.status === "approved" && b.welcome_message && <Notice tone="signal">{b.welcome_message}</Notice>}
      {d.tax_form_required && !d.has_tax_form && (
        <Notice>
          This program needs a signed tax form (W-9 or W-8) before it can pay you.{" "}
          {preview ? <span className="text-muted">(they see a link to the form here)</span> : <Link className="link" href="/a/payouts#tax">Fill it in →</Link>}
        </Notice>
      )}

      <Card title="Your links" className="overflow-hidden" actions={accent && <span className="h-2.5 w-10 rounded-full" style={{ background: accent }} />}>
        <div className="flex items-center gap-2">
          <code className="min-w-0 flex-1 truncate rounded-lg border border-line bg-sunk/60 px-3 py-2 font-mono text-sm">{d.link}</code>
          <CopyButton text={d.link} />
        </div>

        {d.links.length > 0 && (
          <ul className="mt-3 space-y-2">
            {d.links.map((l) => (
              <li key={l.id} className="flex items-center gap-2">
                <div className="min-w-0 flex-1">
                  <code className="block truncate rounded-lg border border-line bg-sunk/60 px-3 py-2 font-mono text-sm">{l.url}</code>
                  {l.label && <p className="mt-0.5 text-xs text-muted">{l.label}</p>}
                </div>
                <CopyButton text={l.url} />
                {!preview && (
                  <form action={deleteOwnLink.bind(null, d.affiliate_id, l.id)}>
                    <button className="btn btn-secondary" title="Stops crediting new visitors">Remove</button>
                  </form>
                )}
              </li>
            ))}
          </ul>
        )}

        {(d.code || d.codes.length > 0) && (
          <div className="mt-4 text-sm">
            <span className="mr-1">Creator code{d.codes.length + (d.code ? 1 : 0) > 1 ? "s" : ""}</span>
            {d.code && <Badge tone="green">{d.code}</Badge>}
            {d.codes.map((c) => <span key={c.id} className="ml-1"><Badge tone={c.redeemable_at_checkout ? "green" : "gray"}>{c.code}</Badge></span>)}
            <p className="mt-1 text-muted">{d.code_redeemable_at_checkout ? "Customers can enter a code at checkout, so it works even without your link." : "Customers can give it when they sign up."}</p>
          </div>
        )}

        <div className="mt-5 rounded-xl border border-dashed border-stone-300 p-4">
          <p className="text-sm font-medium">Test my link</p>
          <p className="mt-1 text-sm text-muted">Opens the site with a test flag. Test clicks aren&apos;t counted, but they show here, so you know tracking is installed.</p>
          <div className="mt-3 flex flex-wrap items-center gap-3">
            <a href={d.test_link} target="_blank" rel="noopener" className="btn btn-secondary">Open test link ↗</a>
            {d.last_test ? (
              <span className="text-sm text-emerald-700">✓ Tracking worked {relative(d.last_test.at)} on <span className="font-mono text-xs">{d.last_test.url.replace(/^https?:\/\//, "").slice(0, 60)}</span></span>
            ) : (
              <span className="text-sm text-muted">No test click recorded yet. Open the link, then refresh this page.</span>
            )}
          </div>
        </div>

        {!preview && (
          <div className="mt-4 space-y-2">
            {d.can_add_links && (
              <details>
                <summary className="cursor-pointer text-sm text-muted">Add a link to a specific page</summary>
                <ActionForm action={addOwnLink} className="mt-3 grid gap-2 sm:grid-cols-[10rem_1fr_10rem_auto]">
                  <input type="hidden" name="id" value={d.affiliate_id} />
                  <input className="input font-mono" name="token" placeholder="jane-yt" pattern="[a-z0-9_\-]{3,32}" required aria-label="Link name" />
                  <input className="input" name="landing_url" type="url" placeholder={`${d.program.website}/pricing`} aria-label="Landing page" />
                  <input className="input" name="label" placeholder="Label (optional)" maxLength={80} aria-label="Label" />
                  <Submit variant="secondary">Add</Submit>
                  <p className="text-xs text-muted sm:col-span-4">Each link has its own name, so you can see which post or video brought a click. Landing pages must be on {d.program.website.replace(/^https?:\/\//, "")}.</p>
                </ActionForm>
              </details>
            )}
            <details>
              <summary className="cursor-pointer text-sm text-muted">Change main link name</summary>
              <ActionForm action={changeToken} className="mt-3 flex flex-wrap items-start gap-2">
                <input type="hidden" name="id" value={d.affiliate_id} />
                <input className="input max-w-xs font-mono" name="token" defaultValue={d.token} pattern="[a-z0-9_\-]{3,32}" required />
                <Submit variant="secondary">Save</Submit>
                <p className="w-full text-xs text-muted">Old links stop crediting new visitors, so update them wherever you posted them.</p>
              </ActionForm>
            </details>
          </div>
        )}
      </Card>

      <section className="grid gap-px overflow-hidden rounded-2xl border border-ink bg-ink-line sm:grid-cols-3">
        <div className="bg-ink px-5 py-5">
          <p className="font-mono text-[11px] uppercase tracking-[0.12em] text-ink-muted">In hold</p>
          <p className="mt-2 truncate font-display text-[2.6rem] leading-none text-white">{bal.in_hold.main}</p>
          {bal.in_hold.rest && <p className="mt-2 text-sm tabular-nums text-ink-muted">{bal.in_hold.rest}</p>}
          <p className="mt-2 text-xs text-ink-muted">{nextRelease ? `next release ${relative(nextRelease)}` : d.program.hold_days ? `released ${d.program.hold_days} days after payment` : "nothing waiting"}</p>
        </div>
        <div className="bg-ink px-5 py-5">
          <p className="font-mono text-[11px] uppercase tracking-[0.12em] text-ink-muted">Payable</p>
          <p className="mt-2 truncate font-display text-[2.6rem] leading-none text-signal" style={accent ? { color: accent } : undefined}>{bal.payable.main}</p>
          {bal.payable.rest && <p className="mt-2 text-sm tabular-nums text-ink-muted">{bal.payable.rest}</p>}
          <p className="mt-2 text-xs text-ink-muted">{`paid out once you reach ${money(d.min_payout_cents)}`}</p>
        </div>
        <div className="bg-ink px-5 py-5">
          <p className="font-mono text-[11px] uppercase tracking-[0.12em] text-ink-muted">Paid to you</p>
          <p className="mt-2 truncate font-display text-[2.6rem] leading-none text-white">{bal.paid.main}</p>
          {bal.paid.rest && <p className="mt-2 text-sm tabular-nums text-ink-muted">{bal.paid.rest}</p>}
          <p className="mt-2 text-xs text-ink-muted">all time</p>
        </div>
      </section>
      {!d.can_be_paid && (
        <p className="-mt-3 text-sm text-muted">
          {preview ? "No payout details saved yet." : <>Tell programs where to send your money: <Link className="link" href="/a/payouts">payout details →</Link></>}
        </p>
      )}

      <StatGroup>
        <Stat label="Clicks" value={d.clicks} hint={`${d.clicks_30d} in the last 30 days`} />
        <Stat label="Signups" value={d.leads} />
        <Stat label="Customers" value={d.customers} />
        <Stat label="Conversion" value={d.clicks ? `${((d.customers / d.clicks) * 100).toFixed(1)}%` : "–"} hint="customers per click" />
      </StatGroup>

      <Card title="Commissions">
        {d.commissions.length === 0 ? (
          <Empty>No commissions yet. You earn when someone you referred pays.</Empty>
        ) : (
          <Table head={["Earned", "For", "Amount", "Status", "When payable"]}>
            {d.commissions.map((c) => (
              <tr key={c.id}>
                <td className="px-5 py-3 text-muted">{date(c.created_at)}</td>
                <td className="px-5 py-3 text-muted">{c.kind === "lead" ? "signup" : c.clawback ? "refund" : "payment"}</td>
                <td className={`num px-5 py-3 ${c.amount_cents < 0 ? "text-red-700" : ""}`}>{money(c.amount_cents, c.currency)}</td>
                <td className="px-5 py-3">
                  <StatusBadge status={c.status} />
                  {c.held_for_review && c.status === "pending" && <span className="ml-1"><Badge tone="amber">under review</Badge></span>}
                  {c.clawback && <p className="mt-1 text-xs text-muted">customer refunded after payout</p>}
                  {c.void_reason && <p className="mt-1 text-xs text-muted">{c.void_reason}</p>}
                </td>
                <td className="px-5 py-3 text-muted">
                  {c.status === "paid" ? `paid ${date(c.paid_at)}` : c.status === "void" ? "" : c.held_for_review ? "after review" : new Date(c.due_at) > new Date() ? `${date(c.due_at)} (${relative(c.due_at)})` : "next payout"}
                </td>
              </tr>
            ))}
          </Table>
        )}
      </Card>
      {d.program.powered_by && (
        <p className="text-center text-xs text-muted">
          Powered by <a className="underline" href="https://kickrail.com/?utm_source=powered_by&utm_medium=portal" target="_blank" rel="noopener">Kickrail</a>
          {" · "}
          <a className="underline" href="https://kickrail.com/signup?utm_source=powered_by&utm_medium=portal" target="_blank" rel="noopener">Run your own affiliate program</a>
        </p>
      )}
    </div>
  );
}
