import type { Metadata } from "next";
import Link from "next/link";
import { SITE } from "../nav";
import { C, Fields, H2, H3, List, Note, P, Snippet, Title } from "../ui";

export const metadata: Metadata = { title: "Install tracking" };

export default function Tracking() {
  return (
    <>
      <Title eyebrow="Get started" lead="With Stripe connected, the script is the only install step. It records affiliate clicks, keeps the referral in a first-party cookie, catches signups from your forms, and hands the referral to Stripe checkouts. It is under 5 KB and has no dependencies.">
        Install tracking
      </Title>

      <H2>Add the script</H2>
      <P>Put this tag on every page of your marketing site and your app, ideally in the <C>&lt;head&gt;</C>. Copy your own from Settings → Install; it already has your public key in it.</P>
      <Snippet label="HTML">{`<script async src="${SITE}/api/kr.js?k=YOUR_PUBLIC_KEY"></script>`}</Snippet>
      <P>The public key (<C>pk_kr_...</C>) only identifies your program. It is safe in page source. Never put your server key (<C>sk_kr_...</C>) in the browser.</P>

      <H2>Affiliate links</H2>
      <P>An affiliate link is any page on your site with the affiliate&apos;s token in the query string:</P>
      <Snippet>{`https://yourapp.com/?via=jane
https://yourapp.com/pricing?via=jane
https://yourapp.com/blog/launch?ref=jane&utm_source=youtube`}</Snippet>
      <P>Kickrail listens for <C>via</C> and <C>ref</C> by default. Change the list in Settings → Program → Link parameters; the first one is used when Kickrail builds links for affiliates. Tokens are matched without regard to case.</P>
      <P>Affiliates can also make extra links with their own tokens and landing pages from their portal, if you leave &quot;Let affiliates create extra links&quot; on. Those resolve to the same affiliate.</P>

      <H2>What happens on a click</H2>
      <List ordered>
        <li>The script generates a click id like <C>kr_7Hq2...</C> (20 random characters after <C>kr_</C>).</li>
        <li>It stores two cookies, <C>kr_ref</C> (the click id) and <C>kr_via</C> (the token), plus a copy in <C>localStorage</C>. Cookies are set on the widest domain your browser allows, so <C>www.yourapp.com</C> and <C>app.yourapp.com</C> share them.</li>
        <li>It sends the click to Kickrail with the page URL and the HTTP referrer, using <C>sendBeacon</C> so it survives an immediate navigation.</li>
      </List>
      <Fields
        head={["Behaviour", "Default", "Notes"]}
        rows={[
          ["Cookie lifetime", "60 days", <>Settings → Program → Cookie window (1 to 365 days). A return visit refreshes it.</>],
          ["Two affiliates", "last click wins", <>Until the visitor signs up. After that the first affiliate keeps them: a later click from someone else does not take the customer.</>],
          ["Cookie flags", "SameSite=Lax", <>Plus <C>Secure</C> on https pages.</>],
        ]}
      />

      <H2>Where the referral goes</H2>
      <P>Once a visitor has a referral, the script attaches it automatically, including to elements added later (it watches the page for changes).</P>
      <H3>Stripe Payment Links</H3>
      <P>Every <C>&lt;a href=&quot;https://buy.stripe.com/...&quot;&gt;</C> gets <C>client_reference_id=kr_...</C> appended. Stripe passes it to the checkout session, and Kickrail credits the purchase. Nothing to change on your side.</P>
      <H3>Pricing tables and buy buttons</H3>
      <P><C>&lt;stripe-pricing-table&gt;</C> and <C>&lt;stripe-buy-button&gt;</C> get a <C>client-reference-id</C> attribute.</P>
      <H3>Signup forms, automatically</H3>
      <P>When a referred visitor submits any form with an email field, like your signup form, the script reports that email to Kickrail. When that person later pays in Stripe with the same email, the affiliate earns the commission. You don&apos;t write any code for this.</P>
      <List>
        <li>Only visitors who arrived through an affiliate link are reported, once per email.</li>
        <li>Login forms (a password field with <C>autocomplete=&quot;current-password&quot;</C>) are skipped.</li>
        <li>A signup caught this way only takes a Stripe customer created after it. An existing customer who clicks an affiliate link and then logs in is not credited.</li>
        <li>It never pays a lead bounty, since the form could be a newsletter box. Report signups yourself (below) if you pay per signup.</li>
        <li>Add <C>data-kickrail-ignore</C> to a form to leave it out.</li>
      </List>
      <H3>Your own forms, by hand</H3>
      <P>Add <C>data-kickrail</C> to a signup or checkout form and the script adds a hidden field named <C>kickrail_referral</C>. Read it on your server and pass it to the <Link className="link" href="/docs/server">referrals API</Link> or to Stripe.</P>
      <Snippet label="HTML">{`<form action="/signup" method="post" data-kickrail>
  <input name="email" type="email">
  <button>Create account</button>
  <!-- added by Kickrail: <input type="hidden" name="kickrail_referral" value="kr_..."> -->
</form>`}</Snippet>
      <H3>Checkout sessions you create (optional)</H3>
      <P>If your server creates Stripe Checkout sessions or customers, you can pass the cookie value along. This is the most exact match and wins over the automatic email match. Kickrail reads all of these:</P>
      <Snippet label="Node">{`stripe.checkout.sessions.create({
  client_reference_id: req.cookies.kr_ref,
  // or: metadata: { kr_ref: req.cookies.kr_ref }
  // ...
});

stripe.customers.create({
  email,
  metadata: { kr_ref: req.cookies.kr_ref }, // kr_via (token) and kr_code (creator code) also work
});`}</Snippet>

      <H2>The browser API</H2>
      <P>The script defines <C>window.Kickrail</C>:</P>
      <Fields
        head={["Member", "Type", "Description"]}
        rows={[
          ["referral", "string | null", <>The click id (<C>kr_...</C>), or null when the visitor was not referred.</>],
          ["token", "string | null", "The affiliate token from the link."],
          ["attach()", "function", "Re-run the Payment Link, pricing table and form tagging by hand."],
          ["convert({ email })", "Promise", <>Report a signup from the browser by hand, for signups that aren&apos;t a plain form submit. Unlike the automatic capture it isn&apos;t limited to new Stripe customers. Ad blockers can stop it, so the <Link className="link" href="/docs/server">server call</Link> is the most reliable.</>],
          ["ready(fn)", "function", "Calls fn with the Kickrail object."],
        ]}
      />
      <P>Because the script loads with <C>async</C>, queue calls that may run before it arrives:</P>
      <Snippet label="JavaScript">{`window.Kickrail = window.Kickrail || { q: [] };
function withKickrail(fn) { Kickrail.loaded ? fn(Kickrail) : Kickrail.q.push(fn); }

withKickrail((k) => {
  if (k.referral) document.querySelector("#ref").value = k.referral;
});`}</Snippet>

      <H2>Serve tracking from your own domain</H2>
      <P>Some ad blockers stop requests to third-party tracking hosts. To avoid that, proxy a path on your own domain to Kickrail and tell the script to use it:</P>
      <List ordered>
        <li>Forward <C>https://yourapp.com/kr/*</C> to <C>{SITE}/api/*</C> (a rewrite in Next.js, Vercel, Netlify, Cloudflare or nginx).</li>
        <li>Load the script through it with <C>api=/kr</C>.</li>
      </List>
      <Snippet label="next.config.js">{`async rewrites() {
  return [{ source: "/kr/:path*", destination: "${SITE}/api/:path*" }];
}`}</Snippet>
      <Snippet label="HTML">{`<script async src="/kr/kr.js?k=YOUR_PUBLIC_KEY&api=/kr"></script>`}</Snippet>

      <H2>Testing a link</H2>
      <P>Add <C>kr_test=1</C> to any affiliate link (<C>?via=jane&amp;kr_test=1</C>). The click is recorded and marked as a test, so you can confirm the script works without inflating the affiliate&apos;s numbers. Affiliates have a &quot;test my link&quot; button in their portal that does the same.</P>
      <Note title="Cookies are not enough on their own">
        Safari limits script-set cookies to 7 days and some browsers block them outright. The cookie only has to survive until signup, but for reliable numbers <Link className="link" href="/docs/server">report signups from your server</Link>. After that, payments are matched by the Stripe customer, so cookies no longer matter.
      </Note>
    </>
  );
}
