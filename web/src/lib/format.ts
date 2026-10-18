export function money(cents: number, currency = "usd") {
  return new Intl.NumberFormat("en-US", { style: "currency", currency: currency.toUpperCase() }).format(cents / 100);
}

/** {usd: 1200, eur: 300} -> "$12.00 · €3.00" */
export function moneyMap(m: Record<string, number> | undefined) {
  const entries = Object.entries(m ?? {}).filter(([, v]) => v !== 0);
  return entries.length ? entries.map(([c, v]) => money(v, c)).join(" · ") : money(0);
}

export function date(iso?: string | null) {
  return iso ? new Date(iso).toLocaleDateString("en-US", { month: "short", day: "numeric", year: "numeric" }) : "";
}

export function relative(iso: string) {
  const days = Math.round((new Date(iso).getTime() - Date.now()) / 86_400_000);
  if (days === 0) return "today";
  return days > 0 ? `in ${days} day${days === 1 ? "" : "s"}` : `${-days} day${days === -1 ? "" : "s"} ago`;
}
