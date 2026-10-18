export function Card({ title, children, actions, className = "", id }: { title?: React.ReactNode; children: React.ReactNode; actions?: React.ReactNode; className?: string; id?: string }) {
  return (
    <section id={id} className={`card ${className}`}>
      {(title || actions) && (
        <div className="-mx-5 -mt-5 mb-5 flex flex-wrap items-center justify-between gap-2 border-b border-line px-5 py-3.5">
          {title && <h2 className="text-[15px] font-semibold tracking-tight">{title}</h2>}
          {actions}
        </div>
      )}
      {children}
    </section>
  );
}

/** A single stat, laid out to sit inside a StatGroup. */
export function Stat({ label, value, hint, big }: { label: string; value: React.ReactNode; hint?: React.ReactNode; big?: boolean }) {
  return (
    <div className="min-w-0 px-5 py-4">
      <p className="eyebrow">{label}</p>
      <p className={`mt-2 truncate leading-none ${big ? "font-display text-[2.6rem]" : "num text-2xl font-medium"}`}>{value}</p>
      {hint && <p className="mt-2 text-xs text-muted">{hint}</p>}
    </div>
  );
}

/** One panel with hairline dividers, so a row of numbers reads as one ledger line instead of N boxes. */
export function StatGroup({ children, cols = 4, className = "" }: { children: React.ReactNode; cols?: 2 | 3 | 4; className?: string }) {
  const grid = { 2: "sm:grid-cols-2", 3: "sm:grid-cols-3", 4: "grid-cols-2 lg:grid-cols-4" }[cols];
  return <div className={`grid gap-px overflow-hidden rounded-2xl border border-line bg-line [&>*]:bg-surface ${grid} ${className}`}>{children}</div>;
}

const TONES: Record<string, [string, string]> = {
  green: ["text-emerald-800", "bg-emerald-500"],
  amber: ["text-amber-800", "bg-amber-500"],
  red: ["text-red-700", "bg-red-500"],
  gray: ["text-stone-600", "bg-stone-400"],
  blue: ["text-sky-800", "bg-sky-500"],
};

export function Badge({ tone = "gray", children }: { tone?: keyof typeof TONES; children: React.ReactNode }) {
  const [text, dot] = TONES[tone];
  return (
    <span className={`inline-flex items-center gap-1.5 rounded-md border border-line bg-surface px-1.5 py-0.5 text-xs font-medium capitalize ${text}`}>
      <span className={`h-1.5 w-1.5 rounded-full ${dot}`} />
      {children}
    </span>
  );
}

export function StatusBadge({ status }: { status: string }) {
  const tone = ({ approved: "green", paid: "green", customer: "green", pending: "amber", awaiting_funding: "amber", processing: "blue", lead: "blue", partial: "amber", rejected: "red", void: "gray", failed: "red", cancelled: "gray", undone: "gray" } as const)[status] ?? "gray";
  return <Badge tone={tone}>{status.replace("_", " ")}</Badge>;
}

export function Empty({ children }: { children: React.ReactNode }) {
  return <p className="rounded-xl border border-dashed border-stone-300 bg-[repeating-linear-gradient(135deg,transparent_0_8px,rgba(0,0,0,0.018)_8px_16px)] p-8 text-center text-sm text-muted">{children}</p>;
}

export function Table({ head, children }: { head: React.ReactNode[]; children: React.ReactNode }) {
  return (
    <div className="-mx-5 -mb-5 overflow-x-auto [&:nth-child(2)]:-mt-5">
      <table className="w-full min-w-[640px] text-sm">
        <thead>
          <tr className="border-b border-line bg-sunk/50 text-left">
            {head.map((h, i) => (
              <th key={i} className="eyebrow px-5 py-2.5 font-normal">
                {h}
              </th>
            ))}
          </tr>
        </thead>
        <tbody className="divide-y divide-line [&_td]:align-top [&_tr]:transition-colors hover:[&_tr]:bg-sunk/30">{children}</tbody>
      </table>
    </div>
  );
}

export function Field({ label, hint, children }: { label: string; hint?: React.ReactNode; children: React.ReactNode }) {
  return (
    <label className="block">
      <span className="text-sm font-medium">{label}</span>
      <div className="mt-1.5">{children}</div>
      {hint && <span className="mt-1.5 block text-xs text-muted">{hint}</span>}
    </label>
  );
}

export function Code({ children }: { children: string }) {
  return <pre className="overflow-x-auto rounded-lg bg-ink p-3 font-mono text-xs leading-relaxed text-stone-200">{children}</pre>;
}

/** Callout for things that need the reader's attention. */
export function Notice({ tone = "amber", children }: { tone?: "amber" | "signal"; children: React.ReactNode }) {
  const cls = tone === "amber" ? "border-amber-300/70 bg-amber-50 text-amber-950" : "border-ink bg-ink text-stone-200";
  return (
    <div className={`flex items-start gap-3 rounded-xl border px-4 py-3 text-sm ${cls}`}>
      <span className={`mt-1.5 h-2 w-2 shrink-0 rounded-full ${tone === "amber" ? "bg-amber-500" : "bg-signal"}`} />
      <div>{children}</div>
    </div>
  );
}
