import Link from "next/link";
import { Logo } from "@/components/Logo";
import { PLANS, planFeatures } from "@/lib/plans";

const POINTS = [
  ["Attribution that survives ad blockers", "Report signups from your server with one API call. The browser script is a fallback, not the source of truth, and it can run through your own domain."],
  ["Creator codes that work at checkout", "Every affiliate code becomes a real Stripe promotion code. Podcast listeners who type JANE20 are credited to Jane without any cookie."],
  ["Pay however you already pay", "Affiliates save their PayPal, Wise or bank details. Pay them your usual way and tick them off, or fund one Stripe payout that reaches everyone."],
  ["Affiliates can see their pipeline", "Clicks, signups, customers, money in hold with its release date, and a test-my-link button that shows the click actually landed."],
  ["Your portal on your domain", "Affiliates sign up and check their earnings at partners.yourdomain.com. Add one DNS record and Kickrail handles the HTTPS certificate."],
  ["Self-referral checks built in", "Matching emails, company domains and sign-in IPs are flagged and their commissions held until you approve them."],
];

// One referral's life, as it appears in the ledger.
const RAIL = [
  ["Click", "?via=janecreator", "landing on /pricing", ""],
  ["Signup", "maya@northwind.io", "reported from your server", ""],
  ["Invoice paid", "CA$50.00", "Pro plan, month 1", ""],
  ["Commission", "CA$15.00", "30% for 12 months", "signal"],
  ["Paid out", "CA$15.00", "PayPal · batch 8HX2", ""],
];

export default function Landing() {
  return (
    <div className="min-h-screen overflow-x-hidden">
      <header className="mx-auto flex max-w-6xl items-center justify-between px-4 py-5 sm:px-6">
        <Logo />
        <nav className="flex items-center gap-2 text-sm">
          <a href="#pricing" className="btn hidden hover:bg-sunk sm:inline-flex">Pricing</a>
          <Link href="/docs" className="btn hidden hover:bg-sunk sm:inline-flex">Docs</Link>
          <Link href="/login" className="btn hover:bg-sunk">Sign in</Link>
          <Link href="/signup" className="btn btn-primary">Start a program</Link>
        </nav>
      </header>

      <main>
        <section className="mx-auto grid max-w-6xl items-center gap-12 px-4 pb-20 pt-12 sm:px-6 lg:grid-cols-[1.15fr_1fr] lg:pt-20">
          <div>
            <p className="eyebrow">Affiliate tracking for Stripe SaaS</p>
            <h1 className="mt-5 font-display text-[3.4rem] leading-[0.95] tracking-tight sm:text-[4.6rem]">
              Every referral,
              <br />
              <span className="italic text-brand">on the record.</span>
            </h1>
            <p className="mt-6 max-w-xl text-lg leading-relaxed text-muted">
              Kickrail follows each referral from the first click to every recurring Stripe invoice, handles refunds and clawbacks, and keeps a ledger your affiliates can check for themselves.
            </p>
            <div className="mt-9 flex flex-wrap gap-3">
              <Link href="/signup" className="btn btn-primary px-5 py-3 text-[15px]">Create your program</Link>
              <Link href="/docs" className="btn btn-secondary px-5 py-3 text-[15px]">Read the docs</Link>
            </div>
          </div>

          <div className="relative">
            <div className="absolute -inset-6 -z-10 rounded-[2rem] bg-[radial-gradient(circle_at_70%_20%,rgba(215,247,91,0.45),transparent_60%)]" />
            <div className="rounded-2xl bg-ink p-5 text-white shadow-[0_30px_60px_-30px_rgba(20,20,15,0.6)]">
              <div className="flex items-center justify-between">
                <p className="font-mono text-[11px] uppercase tracking-[0.12em] text-ink-muted">Referral · janecreator</p>
                <span className="flex items-center gap-1.5 font-mono text-[11px] text-signal">
                  <span className="h-1.5 w-1.5 animate-pulse rounded-full bg-signal" /> live
                </span>
              </div>
              <ol className="relative mt-5">
                <span className="absolute bottom-3 left-[7px] top-3 w-px bg-ink-line" />
                {RAIL.map(([step, value, note, tone]) => (
                  <li key={step} className="relative flex items-start gap-4 py-2.5">
                    <span className={`relative mt-1 h-[15px] w-[15px] shrink-0 rounded-full border-2 ${tone ? "border-signal bg-signal" : "border-ink-muted bg-ink"}`} />
                    <div className="flex min-w-0 flex-1 items-baseline justify-between gap-3">
                      <div className="min-w-0">
                        <p className="text-sm font-medium">{step}</p>
                        <p className="truncate text-xs text-ink-muted">{note}</p>
                      </div>
                      <p className={`shrink-0 font-mono text-sm ${tone ? "text-signal" : "text-stone-300"}`}>{value}</p>
                    </div>
                  </li>
                ))}
              </ol>
              <div className="mt-4 flex items-center justify-between rounded-xl bg-ink-2 px-4 py-3">
                <p className="text-xs text-ink-muted">Recurring for 12 months</p>
                <p className="font-display text-2xl">CA$180.00</p>
              </div>
            </div>
          </div>
        </section>

        <section className="border-y border-line bg-line">
          <div className="mx-auto grid max-w-6xl gap-px bg-line sm:grid-cols-2 lg:grid-cols-3">
            {POINTS.map(([t, d], i) => (
              <div key={t} className="bg-surface px-4 py-8 sm:px-6">
                <p className="font-mono text-xs text-muted">{String(i + 1).padStart(2, "0")}</p>
                <h3 className="mt-3 text-[17px] font-semibold tracking-tight">{t}</h3>
                <p className="mt-2 text-sm leading-relaxed text-muted">{d}</p>
              </div>
            ))}
          </div>
        </section>

        <section id="pricing" className="mx-auto max-w-6xl scroll-mt-6 px-4 pt-20 sm:px-6">
          <p className="eyebrow">Pricing</p>
          <h2 className="mt-2 max-w-2xl font-display text-4xl leading-tight tracking-tight sm:text-5xl">A flat monthly price. No cut of your sales.</h2>
          <p className="mt-4 max-w-2xl text-muted">0% transaction fees on every plan. Every new program gets a 14-day Growth trial, no card needed. Yearly billing gives you 2 months free. Prices are per program.</p>
          <div className="mt-10 grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
            {PLANS.map((p) => (
              <div key={p.id} className={`card flex flex-col p-6 ${p.id === "growth" ? "ring-2 ring-signal" : ""}`}>
                <div className="flex items-center justify-between">
                  <p className="font-medium">{p.name}</p>
                  {p.id === "growth" && <span className="rounded-md bg-signal px-1.5 py-0.5 text-xs font-semibold text-ink">Popular</span>}
                </div>
                <p className="mt-3"><span className="font-display text-4xl">${p.month}</span><span className="text-sm text-muted">{p.month ? "/mo" : ""}</span></p>
                <p className="mt-1 h-4 text-xs text-muted">{p.year ? `or $${p.year.toLocaleString("en-US")}/yr` : "free forever"}</p>
                <ul className="mt-5 flex-1 space-y-2 text-sm text-muted">
                  {planFeatures(p).map((f) => <li key={f}>{f === "API and webhooks" ? <Link href="/docs/api" className="link">{f}</Link> : f}</li>)}
                </ul>
                <Link href="/signup" className={`btn mt-6 w-full ${p.id === "growth" ? "btn-primary" : "btn-secondary"}`}>{p.id === "free" ? "Start free" : "Start a free trial"}</Link>
              </div>
            ))}
          </div>
          <p className="mt-4 text-sm text-muted">Going over your plan&apos;s revenue never stops tracking. If you&apos;re over two months in a row, we&apos;ll suggest the plan that fits. <Link href="/docs/plans" className="link">Full plan details</Link>.</p>
        </section>

        <section className="mx-auto flex max-w-6xl flex-wrap items-end justify-between gap-6 px-4 py-20 sm:px-6">
          <h2 className="max-w-xl font-display text-4xl leading-tight tracking-tight sm:text-5xl">Launch your affiliate program this afternoon.</h2>
          <Link href="/signup" className="btn btn-signal px-5 py-3 text-[15px]">Create your program →</Link>
        </section>
      </main>
    </div>
  );
}
