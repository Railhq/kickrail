"use client";

import { useEffect, useState } from "react";
import { startRewardfulImport } from "@/app/actions";
import { ActionForm, Submit } from "@/components/ActionForm";
import { Badge } from "@/components/ui";
import { date } from "@/lib/format";
import type { Import } from "@/lib/types";

const STEPS = ["campaigns", "affiliates", "referrals", "commissions", "payouts"];
const TONE = { running: "amber", done: "green", failed: "red", stopped: "red" } as const;

export function RewardfulImport({ initial }: { initial: Import | null }) {
  const [imp, setImp] = useState(initial);
  useEffect(() => setImp(initial), [initial]);
  const running = imp?.status === "running";
  useEffect(() => {
    if (!running) return;
    const t = setInterval(async () => {
      const r = await fetch("/api/merchant/import", { cache: "no-store" }).catch(() => null);
      if (r?.ok) setImp((await r.json()).import);
    }, 2000);
    return () => clearInterval(t);
  }, [running]);

  return (
    <>
      <p className="text-sm text-muted">
        Paste your Rewardful API secret (Rewardful → Company settings → API) and Kickrail copies over your campaigns, affiliates with their links and coupon codes, referrals with their Stripe
        customers, commissions and paid payouts. Old <code>?via=</code> links keep working, renewals keep crediting the same affiliate, and unpaid commissions stay owed. The secret is used for this
        run only and never stored. Running it again updates what was imported instead of adding copies.
      </p>
      {imp && (
        <div className="mt-4 rounded-xl border border-line bg-sunk/50 p-3 text-sm">
          <div className="flex flex-wrap items-center gap-2">
            <Badge tone={TONE[imp.status]}>{imp.status === "running" ? `importing ${imp.step}` : imp.status}</Badge>
            <span className="text-muted">Started {date(imp.started_at)}{imp.finished_at && `, finished ${date(imp.finished_at)}`}</span>
          </div>
          <ul className="mt-2 grid grid-cols-2 gap-x-6 gap-y-1 sm:grid-cols-5">
            {STEPS.map((s) => (
              <li key={s}>
                <span className="capitalize">{s}</span>: {imp.counts[s] ?? 0}
                {imp.totals[s] ? <span className="text-muted"> of {imp.totals[s]}</span> : null}
              </li>
            ))}
          </ul>
          {imp.error && <p className="mt-2 text-red-600">{imp.error}</p>}
          {imp.status === "stopped" && <p className="mt-2 text-red-600">The import stopped partway. Run it again: it picks up everything without making copies.</p>}
          {imp.warnings.length > 0 && (
            <details className="mt-2">
              <summary className="cursor-pointer">{imp.warnings.length} note{imp.warnings.length === 1 ? "" : "s"}</summary>
              <ul className="mt-1 list-disc space-y-1 pl-5 text-muted">{imp.warnings.map((w) => <li key={w}>{w}</li>)}</ul>
            </details>
          )}
        </div>
      )}
      {!running && (
        <ActionForm action={startRewardfulImport} className="mt-4 space-y-3">
          <input className="input font-mono text-xs" name="api_secret" type="password" autoComplete="off" placeholder="Rewardful API secret" required aria-label="Rewardful API secret" />
          <label className="flex items-start gap-2 text-sm">
            <input type="checkbox" name="send_claim_emails" className="mt-1" />
            <span>
              Email imported affiliates a link to set their Kickrail password. Logins can&apos;t move over from Rewardful. Each person gets this once; leave it off to tell them yourself first.
            </span>
          </label>
          <Submit variant="secondary">{imp ? "Import again" : "Import from Rewardful"}</Submit>
        </ActionForm>
      )}
    </>
  );
}
