"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";

// 16px stroke icons, one path each.
const ICONS: Record<string, string> = {
  overview: "M2.5 13.5h11M4 11V8m4 3V4.5m4 6.5V6.5",
  affiliates: "M6 7.5a2.25 2.25 0 1 0 0-4.5 2.25 2.25 0 0 0 0 4.5Zm-3.5 6a3.5 3.5 0 0 1 7 0m1.25-6.25a1.75 1.75 0 1 0 0-3.5m1.25 9.75a3 3 0 0 0-1.75-2.75",
  referrals: "M3 4.5h10M3 8h10M3 11.5h6",
  commissions: "M8 2.5v11M10.75 5.25C10.75 4.25 9.5 3.75 8 3.75s-2.75.6-2.75 1.75S6.5 7.1 8 7.5s2.75.85 2.75 2-1.25 1.75-2.75 1.75-2.75-.5-2.75-1.5",
  payouts: "M2.5 5h11v7.5h-11zM2.5 7.5h11M10 10.25h1.5",
  campaigns: "M3 13V3m0 .75h8.5l-1.75 2.5 1.75 2.5H3",
  tax: "M4 2.5h5.5L12 5v8.5H4zM9.5 2.5V5H12M6 8h4M6 10.5h4",
  team: "M5.5 7a2 2 0 1 0 0-4 2 2 0 0 0 0 4Zm5 0a2 2 0 1 0 0-4M2 13a3.5 3.5 0 0 1 7 0m2-3a3 3 0 0 1 3 3",
  developers: "M5.5 5 2.5 8l3 3m5-6 3 3-3 3M9 3.5l-2 9",
  emails: "M2.5 4h11v8h-11zM2.5 4.5 8 8.75l5.5-4.25",
  billing: "M2.5 4.5h11v7h-11zM2.5 6.75h11M4.5 9.5h2",
  docs: "M4 2.5h6l2 2v9H4zM6 7h4M6 9.5h4M6 12h2",
  settings: "M8 10a2 2 0 1 0 0-4 2 2 0 0 0 0 4Zm0-7.5v1.25m0 8.5v1.25M2.5 8h1.25m8.5 0h1.25M4.1 4.1l.9.9m6 6 .9.9m0-7.8-.9.9m-6 6-.9.9",
};

const ITEMS = [
  ["/dashboard", "Overview", "overview"],
  ["/dashboard/affiliates", "Affiliates", "affiliates"],
  ["/dashboard/referrals", "Referrals", "referrals"],
  ["/dashboard/commissions", "Commissions", "commissions"],
  ["/dashboard/payouts", "Payouts", "payouts"],
  ["/dashboard/campaigns", "Campaigns", "campaigns"],
  ["/dashboard/tax", "Tax forms", "tax"],
  ["/dashboard/team", "Team", "team"],
  ["/dashboard/developers", "Developers", "developers"],
  ["/dashboard/emails", "Emails", "emails"],
  ["/dashboard/billing", "Billing", "billing"],
  ["/dashboard/settings", "Settings", "settings"],
  ["/docs", "Docs", "docs"],
];

export function Nav({ flagged }: { flagged: number }) {
  const path = usePathname();
  return (
    <nav className="flex gap-0.5 overflow-x-auto md:flex-col">
      {ITEMS.map(([href, label, icon]) => {
        const active = href === "/dashboard" ? path === href : path.startsWith(href);
        return (
          <Link
            key={href}
            href={href}
            className={`relative flex items-center gap-2.5 whitespace-nowrap rounded-lg px-3 py-2 text-sm transition ${active ? "bg-ink-2 text-white" : "text-ink-muted hover:bg-ink-2/60 hover:text-white"}`}
          >
            {active && <span className="absolute inset-y-2 left-0 hidden w-0.5 rounded-full bg-signal md:block" />}
            <svg width="16" height="16" viewBox="0 0 16 16" fill="none" stroke="currentColor" strokeWidth="1.4" strokeLinecap="round" strokeLinejoin="round" className={active ? "text-signal" : ""} aria-hidden>
              <path d={ICONS[icon]} />
            </svg>
            {label}
            {href === "/dashboard/referrals" && flagged > 0 && <span className="ml-auto rounded-md bg-amber-400 px-1.5 text-xs font-semibold text-ink">{flagged}</span>}
          </Link>
        );
      })}
    </nav>
  );
}
