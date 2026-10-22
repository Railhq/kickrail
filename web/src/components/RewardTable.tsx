import Link from "next/link";
import { fulfillReward, unfulfillReward } from "@/app/actions";
import { ActionForm, Submit } from "@/components/ActionForm";
import { Badge, StatusBadge, Table } from "@/components/ui";
import { date } from "@/lib/format";
import type { Reward } from "@/lib/types";

const WHEN = { signup: "signup", first_payment: "first payment", every_payment: "payment" } as const;

export function RewardTable({ rows, withCustomer = true }: { rows: Reward[]; withCustomer?: boolean }) {
  return (
    <Table compact head={["Reward", "For", ...(withCustomer ? ["Customer"] : []), "Earned", "Status", ""]}>
      {rows.map((w) => (
        <tr key={w.id}>
          <td className="px-3 py-3 first:pl-5 last:pr-5">
            <p className="font-medium">{w.description}</p>
            <p className="text-xs text-muted">on {WHEN[w.trigger]}</p>
          </td>
          <td className="px-3 py-3 first:pl-5 last:pr-5">
            {w.recipient === "affiliate" ? (
              <>Affiliate{w.affiliate_name !== undefined && <> · <Link className="link" href={`/dashboard/affiliates/${w.affiliate_id}`}>{w.affiliate_name || "unnamed"}</Link></>}</>
            ) : (
              "Referred customer"
            )}
          </td>
          {withCustomer && (
            <td className="px-3 py-3 first:pl-5 last:pr-5">
              <Link className="link break-all" href={`/dashboard/referrals/${w.referral_id}`}>{w.customer_email || "referral"}</Link>
            </td>
          )}
          <td className="whitespace-nowrap px-3 py-3 first:pl-5 last:pr-5">{date(w.created_at)}</td>
          <td className="px-3 py-3 first:pl-5 last:pr-5">
            <div className="flex flex-wrap gap-1">
              <StatusBadge status={w.status} />
              {w.held && w.status === "earned" && <Badge tone="amber">held</Badge>}
            </div>
            {w.status === "fulfilled" && <p className="mt-1 text-xs text-muted">{w.fulfilled_at && date(w.fulfilled_at)}{w.note && <> · {w.note}</>}</p>}
            {w.status === "void" && w.void_reason && <p className="mt-1 text-xs text-muted">{w.void_reason}</p>}
          </td>
          <td className="px-3 py-3 first:pl-5 last:pr-5 text-right">
            {w.status === "earned" && !w.held && (
              <ActionForm action={fulfillReward.bind(null, w.id)} className="flex justify-end gap-2">
                <input className="input w-40 py-1 text-xs" name="note" placeholder="Note (optional)" maxLength={300} aria-label="Note" />
                <Submit variant="secondary" className="whitespace-nowrap">Mark fulfilled</Submit>
              </ActionForm>
            )}
            {w.status === "earned" && w.held && <span className="text-xs text-muted">Approve the referral first</span>}
            {w.status === "fulfilled" && (
              <form action={unfulfillReward.bind(null, w.id)}>
                <button className="text-xs text-muted hover:text-fg hover:underline">Undo</button>
              </form>
            )}
          </td>
        </tr>
      ))}
    </Table>
  );
}
