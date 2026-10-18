import type { Metadata } from "next";
import Link from "next/link";
import { SITE } from "../nav";
import { C, Endpoint, Fields, H2, H3, List, Note, P, Snippet, Title } from "../ui";

export const metadata: Metadata = { title: "API reference" };

const BASE = `${SITE}/api/v1`;
const G = "Growth+";

const LIST = (filters: [string, string, React.ReactNode][]) => (
  <Fields
    head={["Query", "Type", "Description"]}
    rows={[
      ["limit", "1 to 100", "How many to return. Default 25."],
      ["starting_after", "id", "Return the page after this object. Pass the last id of the previous page."],
      ...filters,
    ]}
  />
);

const RULE = <>An object: <C>{`{"type": "percent", "percent": 40}`}</C>, <C>{`{"type": "flat", "flat_cents": 1500, "currency": "usd"}`}</C> or <C>{`{"type": "none"}`}</C>. Replaces the campaign rate for this affiliate.</>;

export default function Api() {
  return (
    <>
      <Title eyebrow="Developers" lead={<>A JSON REST API over HTTPS at <C>{BASE}</C>. Reporting and looking up signups works on every plan; everything else needs Growth or Scale.</>}>
        API reference
      </Title>

      <H2>Authentication</H2>
      <P>Send your program&apos;s server key as a bearer token. Find it in Settings → Server API key. Keys start with <C>sk_kr_</C>, belong to one program, and must stay on your server.</P>
      <Snippet label="curl">{`curl ${BASE}/affiliates \\
  -H "Authorization: Bearer sk_kr_..."`}</Snippet>
      <P>There is one key per program. Rolling it in Settings replaces it at once, and the old key stops working immediately. Running several programs? Each has its own key, and a key only sees its own program.</P>

      <H2>Requests and responses</H2>
      <List>
        <li>Send bodies as JSON with <C>Content-Type: application/json</C>.</li>
        <li>Times are ISO 8601 in UTC. Money is an integer in the currency&apos;s smallest unit (<C>1500</C> USD is $15.00) with a lowercase <C>currency</C>.</li>
        <li>Ids carry a prefix: <C>aff_</C>, <C>ref_</C>, <C>com_</C>, <C>po_</C>, <C>cmp_</C>.</li>
      </List>

      <H3>Pagination</H3>
      <P>List endpoints return the newest first:</P>
      <Snippet>{`{ "object": "list", "data": [ ... ], "has_more": true }`}</Snippet>
      <P>To get the next page, pass the last id you received as <C>starting_after</C>, and keep going while <C>has_more</C> is true.</P>
      <Snippet label="Node">{`async function* all(path) {
  let after;
  while (true) {
    const url = new URL("${BASE}" + path);
    url.searchParams.set("limit", "100");
    if (after) url.searchParams.set("starting_after", after);
    const res = await fetch(url, { headers: { Authorization: "Bearer " + process.env.KICKRAIL_SECRET_KEY } });
    const page = await res.json();
    yield* page.data;
    if (!page.has_more) return;
    after = page.data.at(-1).id;
  }
}

for await (const c of all("/commissions?status=pending")) console.log(c.id, c.amount_cents);`}</Snippet>

      <H3>Errors</H3>
      <P>Errors use standard HTTP status codes with a JSON body: <C>{`{"detail": "no such affiliate"}`}</C>. For 422 from validation, <C>detail</C> is a list of the fields that failed.</P>
      <Fields
        head={["Status", "Meaning", ""]}
        rows={[
          ["401", "bad key", "Missing, malformed, or rolled server key."],
          ["402", "plan", "This endpoint needs a higher plan. The message names it."],
          ["404", "not found", "No object with that id in this program."],
          ["409", "conflict", "A token or code is already taken."],
          ["422", "invalid", "A field failed validation."],
        ]}
      />

      <H2>Referrals</H2>

      <Endpoint method="POST" path="/v1/referrals" plan="All plans" />
      <P>Tell Kickrail who signed up and what referred them. Full guide: <Link className="link" href="/docs/server">Report signups from your server</Link>.</P>
      <Fields
        rows={[
          ["referral", "string", <>The <C>kr_ref</C> cookie or <C>kickrail_referral</C> form value.</>],
          ["via", "string", "An affiliate link token."],
          ["code", "string", "A creator code typed at signup."],
          ["email", "string", "The user's email."],
          ["user_id", "string", "Your id for the user, up to 200 characters."],
          ["stripe_customer_id", "string", <><C>cus_...</C></>],
          ["ip", "string", "Signup IP, for the self-referral check. Stored hashed."],
        ]}
      />
      <P>At least one of <C>email</C>, <C>user_id</C>, <C>stripe_customer_id</C> is required. Returns <C>{`{"referred": false}`}</C> or <C>{`{"referred": true, "created": bool, "referral": {...}}`}</C>.</P>

      <Endpoint method="GET" path="/v1/referrals/lookup" plan="All plans" />
      <P>Query with one of <C>email</C>, <C>user_id</C> or <C>stripe_customer_id</C>. Returns <C>{`{"referred": bool, "referral": {...} | null}`}</C>.</P>

      <Endpoint method="GET" path="/v1/referrals" plan={G} />
      {LIST([
        ["affiliate_id", "id", "Only this affiliate's referrals."],
        ["status", "lead | customer", "Lead: signed up. Customer: has paid."],
      ])}

      <Endpoint method="GET" path="/v1/referrals/{id}" plan={G} />

      <H3>The referral object</H3>
      <Fields
        rows={[
          ["id", "string", <><C>ref_...</C></>],
          ["affiliate_id", "string", "Who referred them."],
          ["campaign_id", "string", "The campaign it earns under."],
          ["source", "link | code", "Whether a link or a creator code made the referral."],
          ["status", "lead | customer", <>Becomes <C>customer</C> on the first payment.</>],
          ["email, user_id, stripe_customer_id", "string | null", "What Kickrail knows about the person."],
          ["flagged", "boolean", "A self-referral check matched and hasn't been cleared."],
          ["rejected", "boolean", "You rejected the referral; it earns nothing."],
          ["first_paid_at", "time | null", "Their first payment."],
          ["created_at", "time", ""],
        ]}
      />

      <H2>Affiliates</H2>

      <Endpoint method="GET" path="/v1/affiliates" plan={G} />
      {LIST([
        ["status", "pending | approved | rejected", ""],
        ["email", "string", "Find one affiliate by email."],
        ["campaign_id", "id", ""],
      ])}

      <Endpoint method="GET" path="/v1/affiliates/{id}" plan={G} />

      <Endpoint method="POST" path="/v1/affiliates" plan={G} />
      <P>Add an affiliate from your own app, for example when a customer opts into your partner program. People without a Kickrail login get one, and the welcome email carries a link to set their password. If they are already an affiliate of this program, that affiliate is returned with <C>created: false</C>.</P>
      <Fields
        rows={[
          ["email", "string, required", ""],
          ["name", "string, required", "1 to 100 characters."],
          ["campaign_id", "id", "Defaults to your default campaign."],
          ["status", "pending | approved", <>Default <C>approved</C>.</>],
          ["token", "string", <>Their link token (<C>?via=</C> value): 3 to 32 of a-z, 0-9, <C>-</C>, <C>_</C>. Generated from the name if left out.</>],
          ["code", "string", "A creator code: 3 to 20 letters and digits. Needs Starter or higher."],
          ["rate_override", "rule", RULE],
          ["metadata", "object", "Up to 20 string keys and values, for your own ids."],
          ["send_welcome_email", "boolean", <>Default <C>true</C>.</>],
        ]}
      />
      <Snippet label="curl">{`curl ${BASE}/affiliates \\
  -H "Authorization: Bearer $KICKRAIL_SECRET_KEY" \\
  -H "Content-Type: application/json" \\
  -d '{"email":"jane@example.com","name":"Jane Doe","code":"JANE20","metadata":{"crm_id":"42"}}'`}</Snippet>

      <Endpoint method="PATCH" path="/v1/affiliates/{id}" plan={G} />
      <P>Send only the fields you want to change. The response is the updated affiliate, plus a <C>warning</C> string when Stripe refused to create a promotion code for a new code.</P>
      <Fields
        rows={[
          ["status", "pending | approved | rejected", "Approving sends the approval email."],
          ["campaign_id", "id", "Move them to another campaign."],
          ["token", "string", "Change their main link token."],
          ["code", "string", "Change their main creator code."],
          ["rate_override", "rule", RULE],
          ["clear_rate_override", "boolean", <>Send <C>true</C> to go back to the campaign rate.</>],
          ["metadata", "object", "Replaces the stored metadata."],
        ]}
      />

      <H3>The affiliate object</H3>
      <Snippet label="JSON">{`{
  "id": "aff_2Lp...",
  "object": "affiliate",
  "status": "approved",
  "email": "jane@example.com",
  "name": "Jane Doe",
  "campaign_id": "cmp_...",
  "token": "jane",
  "link": "https://yourapp.com/?via=jane",
  "code": "JANE20",
  "code_redeemable_at_checkout": true,
  "links": [
    { "id": "lnk_...", "token": "jane-yt", "url": "https://yourapp.com/pricing?via=jane-yt",
      "landing_url": "https://yourapp.com/pricing", "label": "YouTube", "created_at": "..." }
  ],
  "codes": [{ "id": "cod_...", "code": "JANEPOD", "redeemable_at_checkout": true, "created_at": "..." }],
  "rate_override": null,
  "metadata": { "crm_id": "42" },
  "created_at": "2026-10-17T15:04:05Z"
}`}</Snippet>
      <P><C>rate_override</C> comes back in stored form: <C>{`{"type": "percent", "bps": 4000}`}</C> (basis points, so 4000 is 40%) or <C>{`{"type": "flat", "cents": 1500, "currency": "usd"}`}</C>.</P>

      <H2>Commissions</H2>
      <Endpoint method="GET" path="/v1/commissions" plan={G} />
      {LIST([
        ["affiliate_id", "id", ""],
        ["referral_id", "id", ""],
        ["status", "pending | paid | void", ""],
      ])}
      <Endpoint method="GET" path="/v1/commissions/{id}" plan={G} />
      <H3>The commission object</H3>
      <Fields
        rows={[
          ["id", "string", <><C>com_...</C></>],
          ["kind", "lead | sale | clawback", <>A lead bounty, a commission on a payment, or a negative amount after a refund of a paid commission.</>],
          ["affiliate_id, referral_id, campaign_id", "string", ""],
          ["amount_cents", "integer", "What the affiliate earns. Negative for a clawback. Shrinks after a partial refund."],
          ["currency", "string", ""],
          ["sale_amount_cents", "integer", "The pre-tax payment it was worked out from."],
          ["status", "pending | paid | void", ""],
          ["held_for_review", "boolean", "Waiting on a self-referral review."],
          ["source", "string", <>Where it came from: <C>inv:in_...</C> (an invoice), <C>cs:cs_...</C> (a one-off checkout), <C>lead:ref_...</C> (a lead bounty) or <C>clawback:...</C>.</>],
          ["due_at", "time", "When the hold ends and it becomes payable."],
          ["paid_at, payout_id", "time, string | null", "Set once it is paid."],
          ["void_reason", "string | null", <>Why it was voided, for example <C>refunded</C>.</>],
          ["created_at", "time", ""],
        ]}
      />

      <H2>Payouts</H2>
      <Endpoint method="GET" path="/v1/payouts" plan={G} />
      {LIST([])}
      <Endpoint method="GET" path="/v1/payouts/{id}" plan={G} />
      <div id="record-payout" />
      <Endpoint method="POST" path="/v1/payouts" plan={G} />
      <P>Record that you paid affiliates yourself, in cash or in kind (a discount, account credit). It works like a manual payout in the dashboard: their payable commissions become <C>paid</C>, they get the payout email if it&apos;s on, and <C>payout.paid</C> goes out. Commissions still in their hold aren&apos;t included. Returns the payout object, or 409 if nothing is payable.</P>
      <Fields
        rows={[
          ["affiliate_ids", "array, required", "1 to 100 affiliate ids, for example the one from a payout.due event."],
          ["currency", "string", "Needed only when those affiliates have payable balances in more than one currency."],
          ["reference", "string", "Up to 200 characters, such as a transfer or coupon id. Shown to you and the affiliate."],
        ]}
      />
      <H3>The payout object</H3>
      <Fields
        rows={[
          ["id", "string", <><C>po_...</C></>],
          ["method", "manual | paypal | stripe", ""],
          ["status", "string", <><C>awaiting_funding</C> until a Stripe batch is paid for, <C>processing</C> while PayPal or Stripe settles, then <C>paid</C>, <C>partial</C> or <C>failed</C>. A manual payout you undo becomes <C>undone</C>.</>],
          ["currency, total_cents, fee_cents", "", ""],
          ["reference", "string", "The reference you typed, or the provider's batch id."],
          ["items", "array", <>One per affiliate: <C>affiliate_id</C>, <C>amount_cents</C>, <C>commission_ids</C>, <C>status</C>, <C>error</C>.</>],
          ["paid_at, created_at", "time", ""],
        ]}
      />

      <H2>Campaigns</H2>
      <Endpoint method="GET" path="/v1/campaigns" plan={G} />
      <P>All campaigns, oldest first, in one list (no pagination). Each has <C>id</C>, <C>name</C>, <C>rule</C>, <C>duration</C>, <C>hold_days</C>, <C>min_payout_cents</C>, <C>lead_bounty</C>, <C>product_rules</C>, <C>stripe_coupon_id</C>, <C>is_default</C>, <C>public</C>, <C>slug</C>, <C>join_url</C> (null for a private campaign), <C>landing_url</C>, and a readable <C>description</C> such as &quot;30% of every payment for 12 months&quot;. Create and edit campaigns in the dashboard.</P>

      <H2>Portal domains</H2>
      <P>Serve the join page and affiliate portal from your own subdomain, as in <Link className="link" href="/docs/portal">Settings → Portal domains</Link>. Adding domains also needs room on your plan (Starter 1, Growth 3, Scale 10).</P>
      <Endpoint method="GET" path="/v1/domains" plan={G} />
      <P>Every domain on the program, in one list.</P>
      <Endpoint method="POST" path="/v1/domains" plan={G} />
      <P>Body: <C>{`{"host": "partners.yourapp.com"}`}</C>. Returns the domain with the <C>dns_record</C> to create, and checks it straight away. The first domain becomes primary.</P>
      <Endpoint method="POST" path="/v1/domains/{host}/verify" plan={G} />
      <P>Checks DNS and HTTPS again, like the Check DNS button. Call it after adding the CNAME; the first check after DNS is verified also requests the certificate.</P>
      <Endpoint method="POST" path="/v1/domains/{host}/primary" plan={G} />
      <P>Makes it the domain used in affiliate links and emails. Returns the full list.</P>
      <Endpoint method="DELETE" path="/v1/domains/{host}" plan={G} />
      <P>Removes it. If it was primary, the next verified domain takes over.</P>
      <H3>The domain object</H3>
      <Fields
        rows={[
          ["host", "string", <><C>partners.yourapp.com</C></>],
          ["status", "string", <><C>not_verified</C> until the CNAME is found, <C>waiting_for_https</C> while the certificate is issued, then <C>live</C>.</>],
          ["primary", "boolean", "Used in affiliate links and emails."],
          ["detail", "string", "Why it isn't live yet, when it isn't."],
          ["dns_record", "object", <><C>{`{"type": "CNAME", "name": host, "value": "portals.kickrail.com"}`}</C></>],
          ["join_url", "string", "The join page on this domain."],
          ["added_at, verified_at, checked_at", "time", ""],
        ]}
      />

      <Note title="Webhooks">
        To react to changes instead of polling, subscribe to <Link className="link" href="/docs/webhooks">webhooks</Link>. Their <C>data</C> uses the same objects as this API.
      </Note>
    </>
  );
}
