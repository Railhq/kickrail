/** Building blocks for the docs pages. */

function slug(s: string) {
  return s.toLowerCase().replace(/[^a-z0-9]+/g, "-").replace(/(^-|-$)/g, "");
}

export function Title({ eyebrow, children, lead }: { eyebrow: string; children: React.ReactNode; lead?: React.ReactNode }) {
  return (
    <div className="mb-10">
      <p className="eyebrow">{eyebrow}</p>
      <h1 className="mt-3 font-display text-[2.75rem] leading-[1.05] tracking-tight">{children}</h1>
      {lead && <p className="mt-4 text-lg leading-relaxed text-muted">{lead}</p>}
    </div>
  );
}

export function H2({ children, id }: { children: string; id?: string }) {
  const a = id ?? slug(children);
  return (
    <h2 id={a} className="group mt-12 scroll-mt-6 font-display text-[1.9rem] leading-tight tracking-tight">
      <a href={`#${a}`}>{children}<span className="ml-2 text-muted opacity-0 group-hover:opacity-100">#</span></a>
    </h2>
  );
}

export function H3({ children, id }: { children: string; id?: string }) {
  const a = id ?? slug(children);
  return <h3 id={a} className="mt-8 scroll-mt-6 font-mono text-[15px] font-semibold">{children}</h3>;
}

export function P({ children }: { children: React.ReactNode }) {
  return <p className="mt-4 leading-relaxed">{children}</p>;
}

export function List({ children, ordered }: { children: React.ReactNode; ordered?: boolean }) {
  const cls = `mt-4 space-y-2 pl-5 leading-relaxed ${ordered ? "list-decimal" : "list-disc"} marker:text-muted`;
  return ordered ? <ol className={cls}>{children}</ol> : <ul className={cls}>{children}</ul>;
}

export function C({ children }: { children: React.ReactNode }) {
  return <code className="rounded bg-sunk px-1 py-0.5 font-mono text-[0.85em]">{children}</code>;
}

export function Snippet({ children, label }: { children: string; label?: string }) {
  return (
    <div className="mt-4 overflow-hidden rounded-xl bg-ink">
      {label && <p className="border-b border-ink-line px-4 py-2 font-mono text-[11px] uppercase tracking-[0.12em] text-ink-muted">{label}</p>}
      <pre className="overflow-x-auto p-4 font-mono text-[13px] leading-relaxed text-stone-200">{children}</pre>
    </div>
  );
}

export function Note({ children, title }: { children: React.ReactNode; title?: string }) {
  return (
    <div className="mt-5 rounded-xl border border-line bg-surface px-4 py-3 text-[15px] leading-relaxed">
      {title && <p className="mb-1 font-medium">{title}</p>}
      <div className="text-muted">{children}</div>
    </div>
  );
}

/** A table of fields or parameters: [name, type, description]. */
export function Fields({ rows, head = ["Field", "Type", "Description"] }: { rows: [string, string, React.ReactNode][]; head?: [string, string, string] }) {
  return (
    <div className="mt-4 overflow-x-auto rounded-xl border border-line bg-surface">
      <table className="w-full text-left text-sm">
        <thead className="border-b border-line">
          <tr>{head.map((h) => <th key={h} className="eyebrow px-4 py-2.5 font-normal">{h}</th>)}</tr>
        </thead>
        <tbody>
          {rows.map(([name, type, desc]) => (
            <tr key={name} className="border-b border-line align-top last:border-0">
              <td className="whitespace-nowrap px-4 py-2.5 font-mono text-[13px] font-medium">{name}</td>
              <td className="whitespace-nowrap px-4 py-2.5 font-mono text-xs text-muted">{type}</td>
              <td className="px-4 py-2.5 leading-relaxed">{desc}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

/** An API endpoint heading: method + path. */
export function Endpoint({ method, path, plan }: { method: string; path: string; plan?: string }) {
  const tone = method === "GET" ? "bg-sunk text-fg" : method === "POST" ? "bg-signal text-ink" : "bg-ink text-white";
  return (
    <div id={slug(`${method} ${path}`)} className="mt-10 flex scroll-mt-6 flex-wrap items-center gap-2 border-t border-line pt-6">
      <span className={`rounded-md px-2 py-0.5 font-mono text-xs font-semibold ${tone}`}>{method}</span>
      <code className="font-mono text-[15px] font-semibold">{path}</code>
      {plan && <span className="rounded-md border border-line px-1.5 py-0.5 text-xs text-muted">{plan}</span>}
    </div>
  );
}
