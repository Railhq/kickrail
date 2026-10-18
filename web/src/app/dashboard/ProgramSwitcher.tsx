import Link from "next/link";
import { switchProgram } from "@/app/actions";
import type { Me } from "@/lib/me";

/** The program box in the sidebar. With several programs it opens a list to switch between them. */
export function ProgramSwitcher({ me }: { me: Me }) {
  const current = me.merchant!;
  const others = me.merchants.filter((p) => p.id !== current.id);
  return (
    <details className="group relative rounded-lg border border-ink-line">
      <summary className="flex cursor-pointer list-none items-center justify-between gap-2 px-3 py-2 [&::-webkit-details-marker]:hidden">
        <span className="min-w-0">
          <span className="block font-mono text-[10px] uppercase tracking-[0.14em] text-ink-muted">Program</span>
          <span className="mt-0.5 block truncate text-sm font-medium">{current.name}</span>
        </span>
        <svg width="12" height="12" viewBox="0 0 12 12" aria-hidden className="shrink-0 text-ink-muted transition group-open:rotate-180">
          <path d="M3 4.5 6 7.5 9 4.5" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round" />
        </svg>
      </summary>
      <div className="absolute inset-x-0 top-full z-20 mt-1 rounded-lg border border-ink-line bg-ink-2 p-1 text-sm shadow-lg">
        {others.map((p) => (
          <form key={p.id} action={switchProgram.bind(null, p.id)}>
            <button className="w-full truncate rounded-md px-2.5 py-1.5 text-left text-stone-200 hover:bg-ink-line hover:text-white">{p.name}</button>
          </form>
        ))}
        <Link href="/onboarding?new" className={`block rounded-md px-2.5 py-1.5 text-ink-muted hover:bg-ink-line hover:text-white ${others.length ? "mt-1 border-t border-ink-line pt-2" : ""}`}>
          + New program
        </Link>
      </div>
    </details>
  );
}
