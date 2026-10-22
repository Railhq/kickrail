import Link from "next/link";

type Params = Record<string, string | undefined>;

/** "/dashboard/referrals" + {q: "jane", page: "2"} -> "/dashboard/referrals?q=jane&page=2", dropping empty values and page 1. */
export function listHref(path: string, params: Params) {
  const qs = new URLSearchParams();
  for (const [k, v] of Object.entries(params)) if (v && !(k === "page" && v === "1")) qs.set(k, v);
  const s = qs.toString();
  return s ? `${path}?${s}` : path;
}

/** A plain GET form, so search works without JavaScript and the URL can be shared. */
export function SearchBox({ path, params, placeholder }: { path: string; params: Params; placeholder: string }) {
  const { q, ...rest } = params;
  const keep = Object.fromEntries(Object.entries(rest).filter(([k]) => k !== "page"));
  return (
    <form action={path} className="flex w-full max-w-md gap-2" role="search">
      {Object.entries(keep).map(([k, v]) => v && <input key={k} type="hidden" name={k} value={v} />)}
      <input className="input min-w-0 flex-1" type="search" name="q" defaultValue={q ?? ""} placeholder={placeholder} aria-label="Search" />
      <button className="btn btn-secondary">Search</button>
      {q && <Link className="btn btn-secondary" href={listHref(path, keep)}>Clear</Link>}
    </form>
  );
}

export function Pager({ path, params, page, total, pageSize }: { path: string; params: Params; page: number; total: number; pageSize: number }) {
  const pages = Math.max(1, Math.ceil(total / pageSize));
  if (total === 0) return null;
  const first = (page - 1) * pageSize + 1;
  const last = Math.min(total, page * pageSize);
  const go = (p: number) => listHref(path, { ...params, page: String(p) });
  return (
    <nav className="flex flex-wrap items-center justify-between gap-3 text-sm text-muted" aria-label="Pages">
      <p className="tabular-nums">
        {first.toLocaleString()}–{last.toLocaleString()} of {total.toLocaleString()}
      </p>
      {pages > 1 && (
        <div className="flex items-center gap-2">
          {page > 1 ? <Link className="btn btn-secondary btn-sm" href={go(page - 1)}>← Newer</Link> : <span className="btn btn-secondary btn-sm pointer-events-none opacity-40">← Newer</span>}
          <span className="tabular-nums">Page {page} of {pages.toLocaleString()}</span>
          {page < pages ? <Link className="btn btn-secondary btn-sm" href={go(page + 1)}>Older →</Link> : <span className="btn btn-secondary btn-sm pointer-events-none opacity-40">Older →</span>}
        </div>
      )}
    </nav>
  );
}
