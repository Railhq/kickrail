"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { DOCS_NAV } from "./nav";

export function DocsNav() {
  const path = usePathname();
  return (
    <nav className="space-y-6 text-sm">
      {DOCS_NAV.map((g) => (
        <div key={g.group}>
          <p className="eyebrow mb-2">{g.group}</p>
          <ul className="space-y-0.5">
            {g.items.map(([href, label]) => (
              <li key={href}>
                <Link href={href} className={`block rounded-md px-2 py-1.5 ${path === href ? "bg-ink font-medium text-white" : "text-muted hover:bg-sunk hover:text-fg"}`}>
                  {label}
                </Link>
              </li>
            ))}
          </ul>
        </div>
      ))}
    </nav>
  );
}

/** Previous / next links at the foot of each page, in sidebar order. */
export function DocsPager() {
  const path = usePathname();
  const flat = DOCS_NAV.flatMap((g) => g.items);
  const i = flat.findIndex(([href]) => href === path);
  if (i < 0) return null;
  const prev = flat[i - 1], next = flat[i + 1];
  return (
    <div className="mt-14 flex justify-between gap-4 border-t border-line pt-6 text-sm">
      {prev ? <Link href={prev[0]} className="link">← {prev[1]}</Link> : <span />}
      {next ? <Link href={next[0]} className="link">{next[1]} →</Link> : <span />}
    </div>
  );
}
