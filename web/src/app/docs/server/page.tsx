import type { Metadata } from "next";
import Link from "next/link";
import { SITE } from "../nav";
import { C, Fields, H2, List, Note, P, Snippet, Title } from "../ui";

export const metadata: Metadata = { title: "Report signups from your server" };

export default function Server() {
  return (
    <>
      <Title eyebrow="Get started" lead="One API call after signup ties the new user to the affiliate who sent them. Ad blockers and browser privacy settings can't interfere with it, and every later Stripe payment from that user is credited automatically. It is available on every plan, including Free.">
        Report signups from your server
      </Title>

      <H2>Get your server key</H2>
      <P>Find it in Settings → Server API key. It starts with <C>sk_kr_</C> and is shown in full only when you create or roll it; after that the dashboard shows just the last four characters. Keep it in an environment variable on your server.</P>
      <P>Each program has one server key, shared by your team. Rolling it in Settings stops the old key immediately, so deploy the new one first.</P>

      <H2>Make the call</H2>
      <P>Right after you create a user, send <C>POST /v1/referrals</C> with whatever you know about them and the referral from the cookie or form field.</P>
      <Snippet label="curl">{`curl ${SITE}/api/v1/referrals \\
  -H "Authorization: Bearer $KICKRAIL_SECRET_KEY" \\
  -H "Content-Type: application/json" \\
  -d '{"referral":"kr_7Hq2...","email":"maya@northwind.io","user_id":"u_1842"}'`}</Snippet>
      <Snippet label="Node (Express)">{`app.post("/signup", async (req, res) => {
  const user = await createUser(req.body);

  // Report it. Don't let a Kickrail hiccup break signup.
  fetch("${SITE}/api/v1/referrals", {
    method: "POST",
    headers: {
      Authorization: "Bearer " + process.env.KICKRAIL_SECRET_KEY,
      "Content-Type": "application/json",
    },
    body: JSON.stringify({
      referral: req.cookies.kr_ref ?? req.body.kickrail_referral,
      email: user.email,
      user_id: user.id,
      stripe_customer_id: user.stripeCustomerId, // if you have one already
      ip: req.ip,                                // for self-referral checks
    }),
  }).catch((err) => console.warn("kickrail", err));

  res.redirect("/welcome");
});`}</Snippet>
      <Snippet label="Python">{`import os, requests

requests.post(
    "${SITE}/api/v1/referrals",
    headers={"Authorization": f"Bearer {os.environ['KICKRAIL_SECRET_KEY']}"},
    json={
        "referral": request.cookies.get("kr_ref"),
        "email": user.email,
        "user_id": str(user.id),
        "ip": request.remote_addr,
    },
    timeout=5,
)`}</Snippet>

      <H2>Body</H2>
      <P>Send at least one of <C>email</C>, <C>user_id</C> or <C>stripe_customer_id</C> (otherwise 422), and at least one way to find the affiliate: <C>referral</C>, <C>via</C> or <C>code</C>.</P>
      <Fields
        rows={[
          ["referral", "string", <>The <C>kr_ref</C> cookie or the <C>kickrail_referral</C> form field. The strongest signal: it points at an actual recorded click.</>],
          ["via", "string", <>The affiliate token, if you only have that (for example the <C>kr_via</C> cookie, or a token you stored yourself).</>],
          ["code", "string", <>A creator code the user typed into your signup form, like <C>JANE20</C>.</>],
          ["email", "string", "The user's email. Also used to match Stripe customers and for the self-referral check."],
          ["user_id", "string", <>Your own id for the user. Lets you look the referral up later with <C>user_id</C>.</>],
          ["stripe_customer_id", "string", <>The Stripe customer (<C>cus_...</C>), if it exists yet. If not, Kickrail matches the customer by email when the first invoice arrives.</>],
          ["ip", "string", "The user's IP address. Stored only as a hash, and compared with the IPs the affiliate signs in from."],
        ]}
      />

      <H2>Response</H2>
      <Snippet label="200">{`{
  "referred": true,
  "created": true,
  "referral": {
    "id": "ref_9xT...",
    "object": "referral",
    "affiliate_id": "aff_2Lp...",
    "campaign_id": "cmp_...",
    "source": "link",
    "status": "lead",
    "email": "maya@northwind.io",
    "user_id": "u_1842",
    "stripe_customer_id": null,
    "flagged": false,
    "rejected": false,
    "first_paid_at": null,
    "created_at": "2026-10-17T15:04:05Z"
  }
}`}</Snippet>
      <List>
        <li><C>{`{"referred": false}`}</C> means nothing pointed at an approved affiliate. That is the normal answer for an organic signup; you can send every signup and let Kickrail decide.</li>
        <li><C>created: false</C> means the person was already attributed. The first affiliate keeps them (or, with last-touch attribution, a newer link or code moves them until their first payment), and the call is safe to repeat.</li>
        <li><C>flagged: true</C> means a self-referral check matched. Commissions for this referral wait for your review.</li>
      </List>

      <H2>Look up a user later</H2>
      <P>To show &quot;referred by Jane&quot; in your admin, or to decide whether to apply a referral discount:</P>
      <Snippet label="curl">{`curl "${SITE}/api/v1/referrals/lookup?user_id=u_1842" \\
  -H "Authorization: Bearer $KICKRAIL_SECRET_KEY"

# {"referred": true, "referral": { ... }}`}</Snippet>
      <P>Pass one of <C>email</C>, <C>user_id</C> or <C>stripe_customer_id</C>. Lookup works on every plan.</P>

      <H2>After signup</H2>
      <P>You don&apos;t report payments. Kickrail receives your Stripe webhooks and matches each <C>invoice.paid</C>, paid <C>checkout.session.completed</C> and <C>payment_intent.succeeded</C> (one-off payments made with Stripe Elements) to the referral by Stripe customer, then by email. Refunds and disputes are handled the same way. See <Link className="link" href="/docs/commissions">Campaigns and commissions</Link>.</P>
      <Note title="Order of signals">
        When several signals arrive, Kickrail trusts them in this order: the click id, the link token, a Stripe promotion code redeemed at checkout, then a creator code typed at signup. Only approved affiliates are credited.
      </Note>
    </>
  );
}
