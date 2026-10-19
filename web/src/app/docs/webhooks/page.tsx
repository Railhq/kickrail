import type { Metadata } from "next";
import Link from "next/link";
import { C, Fields, H2, List, Note, P, Snippet, Title } from "../ui";

export const metadata: Metadata = { title: "Webhooks" };

export default function Webhooks() {
  return (
    <>
      <Title eyebrow="Developers" lead="Kickrail can POST a signed JSON event to your server whenever an affiliate, referral, commission or payout changes. Use it to sync your CRM, post to Slack, or credit referral rewards in your own app. Webhooks need Growth or Scale.">
        Webhooks
      </Title>

      <H2>Add an endpoint</H2>
      <List ordered>
        <li>In the dashboard, open <b>Developers</b> and add your URL. It must be public <C>https</C>; private and local addresses are refused.</li>
        <li>Pick the events to receive, or &quot;All events&quot;, which also includes event types added later.</li>
        <li>Copy the signing secret (<C>whsec_...</C>) into your server&apos;s environment.</li>
        <li>Click <b>Send test</b>. Kickrail sends a <C>ping</C> event at once and shows what your server answered.</li>
      </List>
      <P>You can have up to 10 endpoints per program. Each shows its last 100 deliveries with the response status and body, and any failed delivery can be retried by hand.</P>

      <H2>Events</H2>
      <Fields
        head={["Event", "data", "When"]}
        rows={[
          ["affiliate.created", "affiliate", "Someone joined, or you added them in the dashboard or API."],
          ["affiliate.updated", "affiliate", <>Approved, rejected or otherwise changed. Includes <C>previous_status</C>.</>],
          ["referral.created", "referral", "A new person was attributed to an affiliate."],
          ["referral.updated", "referral", <>Under last-touch attribution, the person moved to another affiliate before paying. Includes <C>previous_affiliate_id</C>.</>],
          ["referral.converted", "referral", <>That person made their first payment (<C>status</C> is now <C>customer</C>).</>],
          ["referral.deleted", "referral", <>You deleted the referral in the dashboard. Its unpaid commissions are deleted with it, each with its own <C>commission.deleted</C>. Has <C>deleted: true</C>.</>],
          ["commission.created", "commission", "An affiliate earned a commission or lead bounty, or a clawback was added after a refund."],
          ["commission.updated", "commission", "A refund shrank or voided it, you released it from review, or you rejected its referral."],
          ["commission.deleted", "commission", <>You deleted it in the dashboard, or deleted its referral. Only unpaid commissions outside a payout can be deleted. Has <C>deleted: true</C>.</>],
          ["payout.due", "payout_due", <>An affiliate&apos;s balance became payable: a commission finished its hold and the balance meets the campaign&apos;s minimum. Sent each time a new commission becomes payable, not again for the same one. Has <C>affiliate_id</C>, <C>campaign_id</C>, <C>email</C>, <C>name</C>, the affiliate&apos;s <C>metadata</C>, <C>currency</C>, <C>amount_cents</C> (the whole payable balance), <C>commission_ids</C> and <C>needs_tax_form</C>. Use it to give a reward in kind, such as a discount, then record it with <Link className="link" href="/docs/api#record-payout">POST /v1/payouts</Link>.</>],
          ["payout.paid", "payout", <>A payout went out. <C>items[].commission_ids</C> lists the commissions it paid.</>],
          ["payout.failed", "payout", "A PayPal or Stripe payout failed in full or in part. The failed commissions are payable again."],
          ["payout.undone", "payout", "You undid a manual payout."],
        ]}
      />
      <P>The objects in <C>data</C> are the same as in the <Link className="link" href="/docs/api">API reference</Link>.</P>

      <H2>Payload</H2>
      <Snippet label="POST https://yourapp.com/kickrail/webhook">{`Content-Type: application/json
User-Agent: Kickrail-Webhooks/1
Kickrail-Event: commission.created
Kickrail-Signature: t=1792252800,v1=5257a869e7ecebeda32affa62cdca3fa51cad7e77a0e56ff536d0ce8e108d8bd

{
  "id": "evt_8sK...",
  "type": "commission.created",
  "created": "2026-10-17T15:04:05.123000+00:00",
  "data": {
    "id": "com_4Zr...",
    "object": "commission",
    "kind": "sale",
    "affiliate_id": "aff_2Lp...",
    "referral_id": "ref_9xT...",
    "amount_cents": 1500,
    "currency": "usd",
    "sale_amount_cents": 5000,
    "status": "pending",
    "held_for_review": false,
    "due_at": "2026-11-16T15:04:05Z",
    ...
  }
}`}</Snippet>

      <H2>Verify the signature</H2>
      <P>Every request carries <C>Kickrail-Signature: t=&lt;unix time&gt;,v1=&lt;hex&gt;</C>, where <C>v1</C> is the HMAC-SHA256 of <C>{"`${t}.${raw body}`"}</C> keyed with your endpoint&apos;s secret. Compute it over the raw request body, before any JSON parsing, compare in constant time, and reject timestamps more than five minutes old so a captured request can&apos;t be replayed.</P>
      <Snippet label="Node (Express)">{`import crypto from "node:crypto";
import express from "express";

const app = express();

app.post("/kickrail/webhook", express.raw({ type: "application/json" }), (req, res) => {
  const header = req.get("Kickrail-Signature") ?? "";
  const { t, v1 } = Object.fromEntries(header.split(",").map((p) => p.split("=")));
  const expected = crypto
    .createHmac("sha256", process.env.KICKRAIL_WEBHOOK_SECRET)
    .update(\`\${t}.\${req.body}\`)
    .digest("hex");
  const fresh = Math.abs(Date.now() / 1000 - Number(t)) < 300;
  const ok = fresh && v1?.length === expected.length &&
    crypto.timingSafeEqual(Buffer.from(v1), Buffer.from(expected));
  if (!ok) return res.status(400).send("bad signature");

  const event = JSON.parse(req.body);
  if (event.type === "commission.created") {
    // ...
  }
  res.sendStatus(200);
});`}</Snippet>
      <Snippet label="Python (Flask)">{`import hashlib, hmac, json, os, time
from flask import Flask, request, abort

app = Flask(__name__)

@app.post("/kickrail/webhook")
def kickrail_webhook():
    body = request.get_data(as_text=True)
    parts = dict(p.split("=", 1) for p in request.headers.get("Kickrail-Signature", "").split(","))
    t, v1 = parts.get("t", "0"), parts.get("v1", "")
    expected = hmac.new(os.environ["KICKRAIL_WEBHOOK_SECRET"].encode(), f"{t}.{body}".encode(), hashlib.sha256).hexdigest()
    if abs(time.time() - int(t)) > 300 or not hmac.compare_digest(v1, expected):
        abort(400)

    event = json.loads(body)
    if event["type"] == "referral.converted":
        ...
    return "", 200`}</Snippet>

      <H2>Delivery and retries</H2>
      <List>
        <li>Any <b>2xx</b> response counts as delivered. Anything else, a timeout (10 seconds) or a connection error is a failure. Redirects are not followed.</li>
        <li>Failures are retried after 1 minute, 5 minutes, 30 minutes, 2 hours, 8 hours and 24 hours. After that the delivery is marked failed; you can still retry it from the dashboard.</li>
        <li>Deliveries can arrive more than once and out of order. Use the event <C>id</C> to skip duplicates, and the object&apos;s current state (or a fresh <C>GET</C> from the API) rather than the order events arrived in.</li>
        <li>Answer quickly and do slow work afterwards, in a queue or background job.</li>
      </List>
      <Note title="Testing locally">
        Kickrail can&apos;t reach <C>localhost</C>. Use a tunnel such as ngrok or Cloudflare Tunnel to get a public https URL, add it as an endpoint, and click Send test.
      </Note>
    </>
  );
}
