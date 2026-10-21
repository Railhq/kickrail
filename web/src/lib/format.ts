export function money(cents: number, currency = "usd") {
  return new Intl.NumberFormat("en-US", { style: "currency", currency: currency.toUpperCase() }).format(cents / 100);
}

/** {usd: 1200, eur: 300} -> "$12.00 · €3.00" */
export function moneyMap(m: Record<string, number> | undefined) {
  const entries = Object.entries(m ?? {}).filter(([, v]) => v !== 0);
  return entries.length ? entries.map(([c, v]) => money(v, c)).join(" · ") : money(0);
}

/** The currency to lead with when amounts come in several: USD if any card has it, else the one with the most money. */
export function mainCurrency(...maps: (Record<string, number> | undefined)[]) {
  const total: Record<string, number> = {};
  for (const m of maps) for (const [c, v] of Object.entries(m ?? {})) if (v) total[c] = (total[c] ?? 0) + Math.abs(v);
  if ("usd" in total) return "usd";
  return Object.entries(total).sort((a, b) => b[1] - a[1])[0]?.[0] ?? "usd";
}

/** {usd: 1200, inr: 50000, cad: 300}, "usd" -> main "$12.00", rest "plus ₹500.00 and CA$3.00" (largest first). */
export function splitMoney(m: Record<string, number> | undefined, main: string) {
  const others = Object.entries(m ?? {})
    .filter(([c, v]) => c !== main && v !== 0)
    .sort((a, b) => b[1] - a[1])
    .map(([c, v]) => money(v, c));
  const rest = others.length ? `plus ${others.length > 1 ? `${others.slice(0, -1).join(", ")} and ${others.at(-1)}` : others[0]}` : null;
  return { main: money(m?.[main] ?? 0, main), rest };
}

export function date(iso?: string | null) {
  return iso ? new Date(iso).toLocaleDateString("en-US", { month: "short", day: "numeric", year: "numeric" }) : "";
}

export function relative(iso: string) {
  const days = Math.round((new Date(iso).getTime() - Date.now()) / 86_400_000);
  if (days === 0) return "today";
  return days > 0 ? `in ${days} day${days === 1 ? "" : "s"}` : `${-days} day${days === -1 ? "" : "s"} ago`;
}

const SOURCES: Record<string, string> = { link: "referral link", code: "creator code", rewardful: "imported from Rewardful" };

export const referralSource = (source: string) => SOURCES[source] ?? source;

/** How to name a referred customer: email, else your user id, else the Stripe customer. */
export const referralWho = (r: { email?: string | null; external_user_id?: string; stripe_customer_id?: string }) => r.email ?? r.external_user_id ?? r.stripe_customer_id ?? "unknown";
