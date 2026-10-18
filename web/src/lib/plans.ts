import type { Plan } from "./types";

export const UNLIMITED = 1e9;

/** Same as backend/app/plans.py. The dashboard reads the live list from /merchant/billing; the home page uses this copy. */
export const PLANS: Plan[] = [
  { id: "free", name: "Free", month: 0, year: 0, revenue_cap: 1_000, domains: 0, campaigns: 1, teammates: 1, creator_codes: false, api: false, stripe_payouts: false, branding: true, priority_support: false },
  { id: "starter", name: "Starter", month: 29, year: 290, revenue_cap: 10_000, domains: 1, campaigns: UNLIMITED, teammates: 3, creator_codes: true, api: false, stripe_payouts: false, branding: true, priority_support: false },
  { id: "growth", name: "Growth", month: 79, year: 790, revenue_cap: 50_000, domains: 3, campaigns: UNLIMITED, teammates: UNLIMITED, creator_codes: true, api: true, stripe_payouts: true, branding: false, priority_support: false },
  { id: "scale", name: "Scale", month: 149, year: 1_490, revenue_cap: 150_000, domains: 10, campaigns: UNLIMITED, teammates: UNLIMITED, creator_codes: true, api: true, stripe_payouts: true, branding: false, priority_support: true },
];

export function planFeatures(p: Plan): string[] {
  const n = (v: number, one: string, many: string) => (v >= UNLIMITED ? `Unlimited ${many}` : `${v} ${v === 1 ? one : many}`);
  return [
    `Up to $${p.revenue_cap.toLocaleString("en-US")}/mo in affiliate revenue${p.id === "scale" ? " (custom pricing above)" : ""}`,
    p.domains ? `${p.domains} custom portal ${p.domains === 1 ? "domain" : "domains"}` : "Portal at kickrail.com/join/your-program",
    n(p.campaigns, "campaign", "campaigns"),
    n(p.teammates, "teammate", "teammates"),
    ...(p.creator_codes ? ["Creator codes redeemable at checkout"] : []),
    ...(p.api ? ["API and webhooks", "Stripe Connect payouts"] : []),
    p.branding ? "Kickrail branding on the portal" : "No Kickrail branding",
    ...(p.priority_support ? ["Priority support"] : []),
  ];
}
