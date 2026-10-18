import type { Metadata } from "next";
import Link from "next/link";
import { SITE } from "./nav";
import { C, H2, List, Note, P, Snippet, Title } from "./ui";

export const metadata: Metadata = { title: { absolute: "Kickrail docs" } };

const CARDS: [string, string, string][] = [
  ["/docs/tracking", "Install tracking", "One script tag. Cookies, Payment Links, pricing tables and your own forms."],
  ["/docs/server", "Report signups from your server", "The call that makes attribution reliable. Works on every plan."],
  ["/docs/codes", "Creator codes", "Codes like JANE20 that work at Stripe checkout with no click at all."],
  ["/docs/commissions", "Campaigns and commissions", "Rates, windows, holds, refunds and self-referral checks."],
  ["/docs/api", "API reference", "Affiliates, referrals, commissions, payouts and campaigns."],
  ["/docs/webhooks", "Webhooks", "Signed events for every change, with retries."],
];

export default function DocsHome() {
  return (
    <>
      <Title eyebrow="Kickrail docs" lead="Kickrail tracks referrals for products that bill with Stripe. A visitor clicks an affiliate's link, signs up, pays an invoice, and the affiliate earns a commission that you pay out. This page gets a program running in about fifteen minutes.">
        Overview and quickstart
      </Title>

      <div className="grid gap-3 sm:grid-cols-2">
        {CARDS.map(([href, t, d]) => (
          <Link key={href} href={href} className="card block transition hover:border-stone-300 hover:bg-white">
            <p className="font-medium">{t}</p>
            <p className="mt-1 text-sm text-muted">{d}</p>
          </Link>
        ))}
      </div>

      <H2>How it works</H2>
      <List ordered>
        <li><b>Click.</b> An affiliate shares <C>https://yourapp.com/?via=jane</C>. The Kickrail script on your site records the click and keeps a referral id in a first-party cookie.</li>
        <li><b>Signup.</b> When the visitor submits your signup form, the script reports their email with the referral id. (Your server can report it instead, with your user id or Stripe customer id.) That ties the person to Jane.</li>
        <li><b>Payment.</b> Kickrail watches your Stripe account. Every paid invoice or one-off checkout from a referred customer earns a commission under the affiliate&apos;s campaign rules.</li>
        <li><b>Refunds.</b> A refund or dispute shrinks or voids an unpaid commission, or claws back a paid one against the next payout.</li>
        <li><b>Payout.</b> Once the hold period passes, the commission is payable. Pay by PayPal, Wise or bank and mark it paid, or send one Stripe payout to everyone.</li>
      </List>

      <H2>Quickstart</H2>
      <P><b>1. Create a program.</b> <Link className="link" href="/signup">Sign up</Link>, then give the program a name and your website. Every new program starts on a 14-day Growth trial with no card.</P>

      <P><b>2. Connect Stripe.</b> In Settings → Stripe, click <b>Connect with Stripe</b> and approve Kickrail on stripe.com. There is nothing to set up in Stripe itself.</P>
      <P>Prefer not to grant OAuth access? Open Developers → API keys → <b>Create restricted key</b> in Stripe, grant the permissions below, and paste the key instead. Kickrail encrypts it and creates its own webhook endpoint on your account.</P>
      <List>
        <li>Customers, Charges, Invoices, Checkout Sessions, Coupons: <b>Read</b></li>
        <li>Promotion Codes, Webhook Endpoints: <b>Write</b></li>
      </List>

      <P><b>3. Add the script</b> to every page of your marketing site and app. Your exact tag, with your public key, is in Settings → Install.</P>
      <Snippet label="HTML">{`<script async src="${SITE}/api/kr.js?k=YOUR_PUBLIC_KEY"></script>`}</Snippet>

      <P>That&apos;s the whole install for most sites. When a referred visitor submits your signup form, the script reports their email, and their first Stripe payment earns the commission.</P>

      <P><b>4. Optional: report signups from your server.</b> For signups that aren&apos;t a plain form, or to rule out ad blockers, send the user&apos;s details and the <C>kr_ref</C> cookie to Kickrail right after you create them. Your server key is in Settings → Server API key.</P>
      <Snippet label="Node">{`await fetch("${SITE}/api/v1/referrals", {
  method: "POST",
  headers: {
    Authorization: "Bearer " + process.env.KICKRAIL_SECRET_KEY,
    "Content-Type": "application/json",
  },
  body: JSON.stringify({
    referral: req.cookies.kr_ref, // set by the script
    email: user.email,
    user_id: user.id,
  }),
});`}</Snippet>

      <P><b>5. Test it.</b> Invite yourself as an affiliate from the Affiliates page (use a different email from your own account, or the self-referral check will hold the commission). Open your affiliate link with <C>&amp;kr_test=1</C> added, sign up, and pay with a Stripe test card. The click, the signup and the commission appear on the Referrals page within a few seconds.</P>

      <Note title="Prefer no code?">
        Steps 1 to 3 need no code beyond the script tag. Stripe Payment Links, pricing tables and buy buttons get the referral too. See <Link className="link" href="/docs/tracking">Install tracking</Link>.
      </Note>

      <H2>Words used in these docs</H2>
      <List>
        <li><b>Program</b>: one product&apos;s affiliate program, with its own Stripe account, affiliates, rules and keys. One login can run several programs.</li>
        <li><b>Affiliate</b>: a person promoting you. Each has a link token (<C>jane</C>), optional extra links, and optional creator codes.</li>
        <li><b>Referral</b>: a person an affiliate brought in. It starts as a <C>lead</C> and becomes a <C>customer</C> on their first payment.</li>
        <li><b>Commission</b>: what an affiliate earned from one payment, or a negative clawback after a refund.</li>
        <li><b>Campaign</b>: the commission rules a group of affiliates is on.</li>
      </List>
    </>
  );
}
