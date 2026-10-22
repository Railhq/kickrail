import { notFound } from "next/navigation";
import { joinProgram } from "@/app/actions";
import { Logo } from "@/components/Logo";
import { api, ApiError } from "@/lib/backend";
import type { Branding } from "@/lib/types";

export type Program = { slug: string; campaign: string | null; name: string; website: string; terms: string | null; hold_days: number | null; branding: Branding; has_terms: boolean; powered_by: boolean };

/** The program's terms: their own page if they gave one, else the one hosted here. */
export function termsHref(p: { slug: string; branding: Branding; has_terms: boolean }) {
  return p.branding.terms_url || (p.has_terms ? `/join/${p.slug}/terms` : null);
}

export async function load(slug: string, campaign?: string) {
  try {
    return await api<Program>(`/programs/${encodeURIComponent(slug)}${campaign ? `/campaigns/${encodeURIComponent(campaign)}` : ""}`, { auth: false });
  } catch (e) {
    if (e instanceof ApiError && e.status === 404) notFound();
    throw e;
  }
}

export function joinMetadata(p: Program) {
  return { title: p.branding.headline || `${p.name} affiliate program`, description: p.branding.description || p.terms || undefined, icons: p.branding.favicon_url ? { icon: p.branding.favicon_url } : undefined };
}

export function JoinView({ p }: { p: Program }) {
  const b = p.branding;
  const terms = termsHref(p);
  return (
    <div className="mx-auto flex min-h-screen max-w-lg flex-col px-4 py-12">
      {b.logo_url ? (
        // eslint-disable-next-line @next/next/no-img-element
        <img src={b.logo_url} alt={p.name} className="h-10 w-auto self-start object-contain" />
      ) : p.powered_by ? (
        <Logo />
      ) : (
        <span className="self-start font-display text-xl tracking-tight">{p.name}</span>
      )}
      <div className="card mt-10 overflow-hidden p-7" style={b.color ? { borderTop: `4px solid ${b.color}` } : undefined}>
        <p className="eyebrow">Affiliate program</p>
        <h1 className="mt-2 font-display text-4xl tracking-tight">{b.headline || p.name}</h1>
        {b.headline && <p className="text-sm font-medium">{p.name}</p>}
        <a href={p.website} className="text-sm text-muted hover:underline" rel="noopener" target="_blank">{p.website.replace(/^https?:\/\//, "")}</a>
        {p.terms && <p className="mt-6 text-lg font-medium">Earn {p.terms}.</p>}
        {b.description && <p className="mt-3 whitespace-pre-line text-sm leading-relaxed">{b.description}</p>}
        <ul className="mt-4 space-y-2 text-sm text-muted">
          <li>• Get a personal link and a creator code customers can type at checkout.</li>
          {p.hold_days != null && <li>• Commissions become payable {p.hold_days} days after each payment, after the refund window.</li>}
          <li>• Paid by PayPal, Wise, bank transfer or Stripe. See every click, signup and commission as it happens.</li>
        </ul>
        <form action={joinProgram.bind(null, p.slug, p.campaign)} className="mt-8">
          <button className="btn btn-primary w-full py-2.5" style={b.color ? { background: b.color, borderColor: b.color } : undefined}>Join program</button>
        </form>
        {terms && <p className="mt-3 text-center text-xs text-muted">By joining you agree to the <a className="underline" href={terms} target="_blank" rel="noopener">program terms</a>.</p>}
        <p className="mt-3 text-center text-xs text-muted">Already promote another Kickrail program? Use the same login.</p>
      </div>
      {p.powered_by && (
        <p className="mt-6 text-center text-xs text-muted">
          Powered by <a className="underline" href="https://kickrail.com/?utm_source=powered_by&utm_medium=portal" target="_blank" rel="noopener">Kickrail</a>
          {" · "}
          <a className="underline" href="https://kickrail.com/signup?utm_source=powered_by&utm_medium=portal" target="_blank" rel="noopener">Run your own affiliate program</a>
        </p>
      )}
    </div>
  );
}
