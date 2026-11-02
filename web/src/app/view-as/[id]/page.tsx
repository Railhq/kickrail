import Link from "next/link";
import { notFound } from "next/navigation";
import { Logo } from "@/components/Logo";
import { PortalView } from "@/components/PortalView";
import { authed } from "@/lib/backend";
import type { PortalView as View } from "@/lib/types";

export const metadata = { title: "View as affiliate" };

/**
 * The merchant's "view as": the affiliate's portal page in the portal's own chrome, outside
 * the dashboard, so it looks the way the affiliate sees it. Read-only, from the merchant's
 * /view endpoint; nothing here signs the merchant in as the affiliate.
 */
export default async function ViewAs({ params }: { params: Promise<{ id: string }> }) {
  const { id } = await params;
  const d = await authed<View & { affiliate: { name: string; email: string } }>(`/merchant/affiliates/${id}/view`, `/view-as/${id}`);
  if (!d) notFound();
  const who = d.affiliate.name || d.affiliate.email;
  return (
    <div className="min-h-screen">
      <div className="sticky top-0 z-20 bg-ink text-sm text-stone-200">
        <div className="mx-auto flex max-w-4xl flex-wrap items-center justify-between gap-3 px-4 py-2.5 sm:px-6">
          <span className="flex min-w-0 items-center gap-2">
            <span className="h-2 w-2 shrink-0 rounded-full bg-signal" />
            <span className="min-w-0 truncate"><b className="text-white">Viewing as {who}.</b> Their portal as they see it, read-only.</span>
          </span>
          <Link href={`/dashboard/affiliates/${id}`} className="rounded-lg border border-ink-line px-2.5 py-1 text-white hover:bg-ink-line">Exit</Link>
        </div>
      </div>
      <header className="border-b border-line bg-bg/85">
        <div className="mx-auto flex max-w-4xl flex-wrap items-center justify-between gap-3 px-4 py-3.5 sm:px-6">
          <div className="flex items-center gap-3">
            <Logo href={`/view-as/${id}`} />
            <span className="rounded-md border border-line px-1.5 py-0.5 font-mono text-[10px] uppercase tracking-[0.12em] text-muted">Affiliate</span>
          </div>
          <nav className="flex items-center gap-1 text-sm text-muted" aria-hidden>
            <span className="px-2.5 py-1.5">Programs</span>
            <span className="px-2.5 py-1.5">Payouts</span>
            <span className="px-2.5 py-1.5">Sign out</span>
          </nav>
        </div>
      </header>
      <main className="mx-auto max-w-4xl px-4 pb-16 pt-10 sm:px-6">
        <PortalView d={d} preview back={<span className="eyebrow">← Programs</span>} />
      </main>
    </div>
  );
}
