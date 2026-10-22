import Link from "next/link";
import { listHref, Pager, SearchBox } from "@/components/ListControls";
import { RewardTable } from "@/components/RewardTable";
import { Card, Empty } from "@/components/ui";
import { api } from "@/lib/backend";
import type { Page, Reward } from "@/lib/types";

export const metadata = { title: "Rewards" };

const PATH = "/dashboard/rewards";
const STATUSES: [string, string][] = [["earned", "To fulfil"], ["fulfilled", "Fulfilled"], ["void", "Void"], ["", "All"]];

export default async function RewardsPage({ searchParams }: { searchParams: Promise<{ status?: string; q?: string; page?: string }> }) {
  const sp = await searchParams;
  // To fulfil is the default view: it's the work left to do.
  const status = sp.status === "" || sp.status === "all" ? undefined : STATUSES.some(([v]) => v && v === sp.status) ? sp.status : "earned";
  const page = Math.max(1, Number.parseInt(sp.page ?? "1", 10) || 1);
  const q = sp.q?.trim() || undefined;
  const qs = new URLSearchParams({ page: String(page) });
  if (status) qs.set("status", status);
  if (q) qs.set("q", q);
  const res = await api<Page<Reward> & { counts: Record<string, number> }>(`/merchant/rewards?${qs}`);
  const params = { status: status ?? "all", q };
  const all = Object.values(res.counts).reduce((a, b) => a + b, 0);
  return (
    <div className="space-y-6">
      <h1 className="page-title">Rewards</h1>
      <p className="text-sm text-muted">
        From campaigns whose reward isn&apos;t cash. Kickrail records who earned what and sends a <code className="font-mono text-xs">reward.earned</code> webhook. Your app hands it out and calls{" "}
        <code className="font-mono text-xs">POST /v1/rewards/&#123;id&#125;/fulfill</code>, or you mark it fulfilled here. A possible self-referral is held until you approve it.
      </p>
      <div className="flex flex-wrap items-center justify-between gap-3">
        <SearchBox path={PATH} params={params} placeholder="Customer email, affiliate or reward" />
        <div className="flex flex-wrap gap-1 text-sm">
          {STATUSES.map(([value, label]) => (
            <Link key={label} href={listHref(PATH, { status: value || "all", q })} className={`btn ${(status ?? "") === value ? "btn-primary" : "btn-secondary"}`}>
              {label} <span className="opacity-70">{value ? res.counts[value] ?? 0 : all}</span>
            </Link>
          ))}
        </div>
      </div>
      <Card>
        {res.items.length === 0 ? (
          <Empty>{q ? `Nothing matches “${q}”.` : all === 0 ? "No rewards yet. Set a campaign's reward to Custom on the Campaigns page, and they appear here as referrals earn them." : "Nothing here."}</Empty>
        ) : (
          <RewardTable rows={res.items} />
        )}
      </Card>
      <Pager path={PATH} params={params} page={res.page} total={res.total} pageSize={res.page_size} />
    </div>
  );
}
