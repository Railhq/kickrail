import { createWebhook, deleteWebhook, retryDelivery, revealWebhookSecret, testWebhook, updateWebhook } from "@/app/actions";
import { ActionForm, Submit } from "@/components/ActionForm";
import { Badge, Card, Code, Empty, Field, Table } from "@/components/ui";
import { api, siteUrl } from "@/lib/backend";
import { date } from "@/lib/format";
import type { Merchant } from "@/lib/types";

export const metadata = { title: "Developers" };

type Endpoint = { id: string; url: string; description: string; events: string[]; enabled: boolean; secret_hint: string; created_at: string };
type Delivery = { id: string; type: string; status: "pending" | "sending" | "delivered" | "failed"; attempts: number; response_status?: number; last_error?: string; next_attempt_at?: string; created_at: string; payload: unknown };

const TONE = { delivered: "green", pending: "amber", sending: "blue", failed: "red" } as const;

function EventPicker({ types, selected }: { types: string[]; selected: string[] }) {
  const all = selected.includes("*");
  return (
    <fieldset>
      <legend className="text-sm font-medium">Events</legend>
      <label className="mt-1.5 flex items-center gap-2 text-sm"><input type="checkbox" name="all_events" defaultChecked={all} /> All events, including ones added later</label>
      <div className="mt-2 grid grid-cols-2 gap-x-4 gap-y-1 sm:grid-cols-3">
        {types.map((t) => (
          <label key={t} className="flex items-center gap-2 font-mono text-xs"><input type="checkbox" name="events" value={t} defaultChecked={!all && selected.includes(t)} /> {t}</label>
        ))}
      </div>
    </fieldset>
  );
}

export default async function DevelopersPage() {
  const [{ endpoints, event_types }, m, site] = await Promise.all([api<{ endpoints: Endpoint[]; event_types: string[] }>("/merchant/webhooks"), api<Merchant>("/merchant"), siteUrl()]);
  const deliveries = await Promise.all(endpoints.map((e) => api<Delivery[]>(`/merchant/webhooks/${e.id}/deliveries`)));
  const verify = `// Verify a webhook (Node). Header: Kickrail-Signature: t=<unix>,v1=<hex>
import crypto from "node:crypto";
function verify(rawBody, header, secret) {
  const { t, v1 } = Object.fromEntries(header.split(",").map((p) => p.split("=")));
  const expected = crypto.createHmac("sha256", secret).update(\`\${t}.\${rawBody}\`).digest("hex");
  const fresh = Math.abs(Date.now() / 1000 - Number(t)) < 300;
  return fresh && crypto.timingSafeEqual(Buffer.from(v1), Buffer.from(expected));
}`;
  const rest = `curl ${site}/api/v1/affiliates?limit=20 \\
  -H "Authorization: Bearer $KICKRAIL_SECRET_KEY"

# Create an approved affiliate and email them a set-password link
curl ${site}/api/v1/affiliates -H "Authorization: Bearer $KICKRAIL_SECRET_KEY" \\
  -H "Content-Type: application/json" \\
  -d '{"email":"jane@example.com","name":"Jane","status":"approved","metadata":{"crm_id":"42"}}'`;
  return (
    <div className="space-y-6">
      <div className="flex flex-wrap items-end justify-between gap-3">
        <h1 className="page-title">Developers</h1>
        <div className="flex gap-2 text-sm"><a className="btn btn-secondary" href="/docs/api">API reference</a><a className="btn btn-secondary" href="/docs/webhooks">Webhook docs</a></div>
      </div>

      <Card title="REST API">
        <p className="text-sm text-muted">
          Authenticate with your server key (<code className="font-mono">{m.secret_key_hint}</code>, roll it in Settings). Lists are newest first and paginate with <code>limit</code> (1 to 100) and <code>starting_after</code>; each returns <code>{"{ object: \"list\", data, has_more }"}</code>.
        </p>
        <ul className="my-3 grid gap-x-6 gap-y-1 font-mono text-xs sm:grid-cols-2">
          {["GET /v1/affiliates", "POST /v1/affiliates", "GET /v1/affiliates/{id}", "PATCH /v1/affiliates/{id}", "GET /v1/referrals", "POST /v1/referrals", "GET /v1/commissions", "GET /v1/payouts", "GET /v1/campaigns"].map((r) => <li key={r}>{r}</li>)}
        </ul>
        <Code>{rest}</Code>
      </Card>

      <Card title="Webhook endpoints">
        {endpoints.length === 0 && <Empty>No endpoints yet. Add one to get affiliate, referral, commission and payout events as they happen.</Empty>}
        <div className="space-y-4">
          {endpoints.map((e, i) => (
            <div key={e.id} className="rounded-xl border border-line p-4">
              <div className="flex flex-wrap items-center gap-2">
                <code className="min-w-0 flex-1 truncate font-mono text-sm">{e.url}</code>
                <Badge tone={e.enabled ? "green" : "gray"}>{e.enabled ? "enabled" : "disabled"}</Badge>
              </div>
              <p className="mt-1 text-xs text-muted">{e.description && `${e.description} · `}{e.events.includes("*") ? "all events" : e.events.join(", ")} · secret {e.secret_hint}</p>
              <div className="mt-3 flex flex-wrap items-start gap-2">
                <ActionForm action={testWebhook}><input type="hidden" name="id" value={e.id} /><Submit variant="secondary">Send test event</Submit></ActionForm>
                <ActionForm action={revealWebhookSecret} secretLabel="Signing secret"><input type="hidden" name="id" value={e.id} /><Submit variant="secondary">Reveal secret</Submit></ActionForm>
                <form action={deleteWebhook.bind(null, e.id)}><button className="btn btn-danger">Delete</button></form>
              </div>
              <details className="mt-3">
                <summary className="cursor-pointer text-sm text-muted">Edit</summary>
                <ActionForm action={updateWebhook} className="mt-3 space-y-3">
                  <input type="hidden" name="id" value={e.id} />
                  <div className="grid gap-3 sm:grid-cols-2">
                    <Field label="URL"><input className="input font-mono text-xs" name="url" defaultValue={e.url} required /></Field>
                    <Field label="Description"><input className="input" name="description" defaultValue={e.description} maxLength={200} /></Field>
                  </div>
                  <EventPicker types={event_types} selected={e.events} />
                  <label className="flex items-center gap-2 text-sm"><input type="checkbox" name="enabled" defaultChecked={e.enabled} /> Enabled</label>
                  <Submit variant="secondary">Save</Submit>
                </ActionForm>
              </details>
              <details className="mt-2" open={deliveries[i].some((d) => d.status === "failed")}>
                <summary className="cursor-pointer text-sm text-muted">Recent deliveries ({deliveries[i].length})</summary>
                {deliveries[i].length === 0 ? (
                  <p className="mt-2 text-sm text-muted">Nothing sent yet.</p>
                ) : (
                  <div className="mt-3 [&>div]:mx-0 [&>div]:mb-0">
                    <Table head={["When", "Event", "Status", "Response", ""]}>
                      {deliveries[i].map((d) => (
                        <tr key={d.id}>
                          <td className="whitespace-nowrap px-5 py-2.5 text-muted">{date(d.created_at)}</td>
                          <td className="px-5 py-2.5">
                            <details>
                              <summary className="cursor-pointer font-mono text-xs">{d.type}</summary>
                              <pre className="mt-2 max-h-64 max-w-md overflow-auto rounded-lg bg-ink p-2 text-[11px] text-stone-200">{JSON.stringify(d.payload, null, 2)}</pre>
                            </details>
                          </td>
                          <td className="px-5 py-2.5">
                            <Badge tone={TONE[d.status]}>{d.status}</Badge>
                            {d.status === "pending" && d.next_attempt_at && <p className="mt-1 text-xs text-muted">retry #{d.attempts + 1} {date(d.next_attempt_at)}</p>}
                          </td>
                          <td className="px-5 py-2.5 text-xs">{d.response_status ?? ""}{d.last_error && <p className="text-red-700">{d.last_error}</p>}</td>
                          <td className="px-5 py-2.5 text-right">{d.status === "failed" && <form action={retryDelivery.bind(null, d.id)}><button className="text-xs underline">retry</button></form>}</td>
                        </tr>
                      ))}
                    </Table>
                  </div>
                )}
              </details>
            </div>
          ))}
        </div>
        {endpoints.length < 10 && (
          <details className="mt-5 border-t border-line pt-4" open={endpoints.length === 0}>
            <summary className="cursor-pointer text-sm font-medium">Add endpoint</summary>
            <ActionForm action={createWebhook} secretLabel="Signing secret" className="mt-3 space-y-3">
              <div className="grid gap-3 sm:grid-cols-2">
                <Field label="URL" hint="Must be https and publicly reachable."><input className="input font-mono text-xs" name="url" placeholder="https://example.com/webhooks/kickrail" required /></Field>
                <Field label="Description"><input className="input" name="description" maxLength={200} /></Field>
              </div>
              <EventPicker types={event_types} selected={["*"]} />
              <Submit>Add endpoint</Submit>
            </ActionForm>
          </details>
        )}
      </Card>

      <Card title="Verifying signatures">
        <p className="mb-3 text-sm text-muted">Every delivery is signed with the endpoint&apos;s secret. Failed deliveries retry with backoff for about a day and a half; answer 2xx to acknowledge.</p>
        <Code>{verify}</Code>
      </Card>
    </div>
  );
}
