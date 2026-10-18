import {
  openExpressDashboard,
  savePayoutDetails,
  startPayoutOnboarding,
} from "@/app/actions";
import { ActionForm, Submit } from "@/components/ActionForm";
import { Badge, Card, Field } from "@/components/ui";
import { api } from "@/lib/backend";
import { date } from "@/lib/format";
import { TaxForm, type TaxInfo } from "./TaxForm";

export const metadata = { title: "Payouts" };

type Details = { method: "paypal" | "wise" | "bank" | "other"; value: string };
type Account = {
  details: Details | null;
  connected: boolean;
  payouts_enabled: boolean;
  stripe_payouts: boolean;
};
type Status = {
  payouts_enabled: boolean;
  connected: boolean;
  state?: "ready" | "verifying" | "needs_info" | "not_connected";
  unavailable?: boolean;
};

const METHODS: [Details["method"], string, string][] = [
  ["paypal", "PayPal", "PayPal email"],
  ["wise", "Wise", "Wise email"],
  [
    "bank",
    "Bank transfer",
    "Account holder, bank, account and routing numbers",
  ],
  ["other", "Other", "How you'd like to be paid"],
];

export default async function PayoutSetup() {
  const [acct, { tax_info }] = await Promise.all([api<Account>("/payout-account"), api<{ tax_info: TaxInfo | null }>("/tax-info")]);
  // Only ask Stripe when there's a Stripe account to check: onboarding returns here.
  const s: Status = acct.connected
    ? await api<Status>("/payout-account/refresh", { method: "POST" }).catch(
        () => ({ payouts_enabled: false, connected: true, unavailable: true }),
      )
    : { payouts_enabled: false, connected: false, state: "not_connected" };
  const d = acct.details;
  return (
    <div className="space-y-6">
      <h1 className="page-title">Payouts</h1>

      <Card
        title="Where to send your money"
        actions={
          d ? (
            <Badge tone="green">saved</Badge>
          ) : (
            <Badge tone="amber">missing</Badge>
          )
        }
      >
        <p className="text-sm text-muted">
          Programs pay you directly. They see these details next to what they
          owe you, and this applies to every program you join.
        </p>
        <ActionForm action={savePayoutDetails} className="mt-4">
          <div className="grid gap-4 sm:grid-cols-[12rem_1fr]">
            <Field label="Method">
              <select
                name="method"
                className="input"
                defaultValue={d?.method ?? "paypal"}
              >
                {METHODS.map(([v, label]) => (
                  <option key={v} value={v}>
                    {label}
                  </option>
                ))}
              </select>
            </Field>
            <Field
              label="Details"
              hint={METHODS.map(([, l, h]) => `${l}: ${h}`).join(" · ")}
            >
              <input
                className="input"
                name="value"
                defaultValue={d?.value ?? ""}
                placeholder="you@example.com"
                required
                minLength={3}
                maxLength={500}
              />
            </Field>
          </div>
          <Submit className="mt-4">{d ? "Update" : "Save"}</Submit>
        </ActionForm>
      </Card>

      <Card
        title={<span id="tax" className="scroll-mt-24">Tax form</span>}
        actions={tax_info ? <Badge tone="green">{`${tax_info.form === "w9" ? "W-9" : tax_info.form === "w8ben" ? "W-8BEN" : "W-8BEN-E"} signed`}</Badge> : <Badge tone="amber">not signed</Badge>}
      >
        <p className="mb-4 text-sm text-muted">
          Some programs need a W-9 or W-8 before they can pay you. Sign once and it applies to every program.
          {tax_info && ` Signed by ${tax_info.signature} on ${date(tax_info.signed_at)}, TIN ending ${tax_info.tin_last4}.`}
        </p>
        {tax_info ? (
          <details>
            <summary className="cursor-pointer text-sm text-muted">Replace it</summary>
            <div className="mt-4"><TaxForm current={tax_info} /></div>
          </details>
        ) : (
          <TaxForm current={null} />
        )}
      </Card>

      {acct.stripe_payouts && (
      <Card
        title="Automatic payouts with Stripe (optional)"
        actions={
          s.payouts_enabled ? (
            <Badge tone="green">ready</Badge>
          ) : s.connected ? (
            <Badge tone="amber">
              {s.state === "verifying" ? "verifying" : "incomplete"}
            </Badge>
          ) : (
            <Badge>not set up</Badge>
          )
        }
      >
        <p className="text-sm text-muted">
          Some programs pay through Stripe instead. Stripe verifies your
          identity once and deposits to your bank, and this one account works
          for every program you join.
        </p>
        {s.unavailable && (
          <p className="mt-3 text-sm text-red-700">
            Stripe payouts aren&apos;t available right now.
          </p>
        )}
        {s.state === "verifying" && (
          <p className="mt-3 text-sm text-muted">
            Stripe is checking your details. This usually takes a few minutes;
            refresh this page to see the result.
          </p>
        )}
        {s.state === "needs_info" && (
          <p className="mt-3 text-sm text-amber-800">
            Stripe needs a few more details before you can be paid. Finish setup
            to see what&apos;s missing.
          </p>
        )}
        <div className="mt-4 flex flex-wrap gap-3">
          {!s.payouts_enabled && s.state !== "verifying" && (
            <ActionForm
              action={startPayoutOnboarding}
              className="flex flex-wrap items-center gap-2"
            >
              {!s.connected && (
                <select
                  name="country"
                  className="input w-auto"
                  defaultValue="US"
                  aria-label="Country"
                >
                  {["US", "CA"].map((c) => (
                    <option key={c}>{c}</option>
                  ))}
                </select>
              )}
              <Submit variant={s.connected ? "primary" : "secondary"}>
                {s.connected
                  ? "Finish setup with Stripe"
                  : "Set up with Stripe"}
              </Submit>
            </ActionForm>
          )}
          {s.connected && (
            <ActionForm action={openExpressDashboard}>
              <Submit variant="secondary">Open Stripe dashboard</Submit>
            </ActionForm>
          )}
        </div>
      </Card>
      )}
    </div>
  );
}
