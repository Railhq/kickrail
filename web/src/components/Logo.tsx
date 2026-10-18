import Link from "next/link";

/** Two rails converging on a signal dot: a referral arriving at a payout. */
export function Mark({ size = 24, dark = false }: { size?: number; dark?: boolean }) {
  return (
    <svg width={size} height={size} viewBox="0 0 24 24" aria-hidden>
      <rect width="24" height="24" rx="7" fill={dark ? "var(--signal)" : "var(--ink)"} />
      <path d="M5.5 7.5h7.5M5.5 12h10M5.5 16.5h7.5" stroke={dark ? "var(--ink)" : "#fff"} strokeWidth="2" strokeLinecap="round" />
      <circle cx="18.5" cy="12" r="2.2" fill={dark ? "var(--ink)" : "var(--signal)"} />
    </svg>
  );
}

export function Logo({ href = "/", dark = false }: { href?: string; dark?: boolean }) {
  return (
    <Link href={href} className={`flex items-center gap-2 text-[17px] font-semibold tracking-tight ${dark ? "text-white" : ""}`}>
      <Mark dark={dark} />
      Kickrail
    </Link>
  );
}
