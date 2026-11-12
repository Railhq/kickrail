"use client";

import { usePathname } from "next/navigation";
import { useEffect } from "react";

type Identity = { enabled: boolean; url?: string; workspace?: string; user?: Record<string, unknown> | null };
type Queue = ((...args: unknown[]) => void) & { q?: unknown[][] };

function helprail(...args: unknown[]) {
  const w = window as unknown as { Helprail?: Queue };
  if (!w.Helprail) {
    const stub: Queue = (...a: unknown[]) => void (stub.q = stub.q || []).push(a);
    w.Helprail = stub;
  }
  w.Helprail(...args);
}

/**
 * The Helprail support chat. Loads on every page except paths matching a `skip` pattern (pages shown to
 * someone other than our customer, or inside other sites) and only on `hosts` when given.
 * Signed-in users are identified through /helprail-identity; everyone else chats anonymously.
 */
export default function HelprailWidget({ skip = [], hosts }: { skip?: string[]; hosts?: string[] }) {
  const pathname = usePathname() || "/";
  const off = skip.some((r) => new RegExp(r).test(pathname));

  useEffect(() => {
    if (off) return;
    if (hosts && !hosts.includes(window.location.hostname)) return;
    let cancelled = false;
    (async () => {
      const res = await fetch("/helprail-identity", { cache: "no-store" }).catch(() => null);
      const id: Identity | null = res?.ok ? await res.json().catch(() => null) : null;
      if (cancelled || !id?.enabled || !id.url || !id.workspace) return;
      helprail("boot", { workspace: id.workspace, ...(id.user || {}) });
      if (!document.getElementById("helprail-script")) {
        const s = document.createElement("script");
        s.id = "helprail-script";
        s.async = true;
        s.src = `${id.url}/widget.js`;
        document.body.appendChild(s);
      }
    })();
    return () => {
      cancelled = true;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [off]);

  // Moving onto a skipped page after the chat started: take it down.
  useEffect(() => {
    if (off && (window as unknown as { Helprail?: Queue }).Helprail) helprail("shutdown");
  }, [off]);

  return null;
}
