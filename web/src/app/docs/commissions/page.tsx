import type { Metadata } from "next";
import { C, Fields, H2, H3, List, Note, P, Snippet, Title } from "../ui";

export const metadata: Metadata = { title: "Campaigns and commissions" };

export default function Commissions() {
  return (
    <>
      <Title eyebrow="Running a program" lead="A campaign is a set of commission rules. Every affiliate is on one campaign, and every program starts with a default one. Payments from a referred customer earn under that campaign's rules.">
        Campaigns and commissions
      </Title>

      <H2>Campaign settings</H2>
      <Fields
        head={["Setting", "Values", "What it does"]}
        rows={[
          ["Rate", "percent or flat", <>A percentage of each payment (for example 30%), or a fixed amount per payment in one currency (for example 10.00 USD).</>],
          ["Duration", "once, months, forever", <>Pay on the first payment only, on every payment for N months after the first one (1 to 120), or on every payment for as long as the customer pays.</>],
          ["Hold", "0 to 180 days", "How long a commission waits before it becomes payable. Set it to cover your refund window."],
          ["Minimum payout", "amount", "An affiliate isn't included in a payout until they are owed at least this much."],
          ["Lead bounty", "amount, optional", "A fixed amount paid once per referred signup, before anyone pays. It does not use up a one-time sale commission."],
          ["Product rules", "up to 50", <>Different rates for specific Stripe products or prices, or <b>no commission</b> to exclude one (a hardware add-on, a low-margin plan).</>],
          ["Stripe coupon", "coupon id, optional", "Makes affiliates' creator codes redeemable at checkout. See Creator codes."],
          ["Public join page", "on or off", <>On: the campaign gets its own join page at <C>/join/your-program/page-name</C>, and people who sign up there join this campaign. Off: invite-only.</>],
          ["Landing page", "URL, optional", "Where this campaign's affiliate links point instead of your website, for example /partners. Must be on your site."],
        ]}
      />
      <P>The Free plan has one campaign. Starter and up can have as many as they like, for example a 20% default and a 40% campaign for top partners. You can also give a single affiliate a <b>rate override</b> that replaces the campaign rate for them alone. Product rules still win for the products they name.</P>
      <H3>Public and private campaigns</H3>
      <P>Your main join page always signs people up to the <b>default</b> campaign. Turn on <b>Public join page</b> for any other campaign to give it a page of its own, so you can send creators to one page and customers to another on different terms. The page shows that campaign&apos;s rate and hold period. A private campaign has no page: you add affiliates to it from the Affiliates page or the API, or move existing affiliates onto it.</P>
      <P>Each campaign can also have its own <b>landing page</b>. Affiliates on it get default links like <C>https://yourapp.com/partners?via=jane</C>, and moving an affiliate to another campaign moves their default link with them. Links an affiliate made themselves keep their own landing page.</P>

      <H2>How a commission is worked out</H2>
      <List ordered>
        <li>Kickrail takes what the customer actually paid, after discounts and before tax.</li>
        <li>It checks the duration: a one-time campaign pays only once per referral, and a 12-month campaign stops 12 months after the first payment.</li>
        <li>With product rules, the payment is split across its invoice lines in proportion to their amounts, and each line gets its own rate.</li>
        <li>The result is in the payment&apos;s currency. It becomes payable on the payment date plus the hold.</li>
      </List>
      <Snippet label="Example">{`Campaign: 30%, 12 months, 30-day hold
Invoice:  CA$56.50 paid, CA$6.50 of it tax

Base        = 56.50 - 6.50 = CA$50.00
Commission  = 30% of 50.00 = CA$15.00
Payable on  = invoice date + 30 days`}</Snippet>
      <P>Kickrail never pays twice for the same payment. Stripe retries webhooks, and a payment can arrive both as a checkout and an invoice; each payment is recorded once.</P>

      <H2>Commission states</H2>
      <Fields
        head={["Status", "Meaning", ""]}
        rows={[
          ["pending", "earned, not paid", <>In its hold until <C>due_at</C>, then payable. <C>held_for_review</C> means it waits for you to clear a self-referral flag first.</>],
          ["paid", "included in a payout", <><C>payout_id</C> and <C>paid_at</C> say which and when.</>],
          ["void", "cancelled", <>A full refund before it was paid. <C>void_reason</C> explains why.</>],
        ]}
      />

      <H2>Refunds and disputes</H2>
      <P>Kickrail listens for <C>charge.refunded</C> and <C>charge.dispute.created</C> on your Stripe account.</P>
      <List>
        <li><b>Not paid yet:</b> a partial refund shrinks the commission in proportion; a full refund voids it.</li>
        <li><b>Already paid:</b> Kickrail adds a negative <b>clawback</b> commission (<C>kind: &quot;clawback&quot;</C>). It nets against the affiliate&apos;s next payout, so nobody has to send money back by hand.</li>
        <li>Several partial refunds add up exactly to the original commission, never more.</li>
      </List>

      <H2>Self-referral checks</H2>
      <P>Kickrail flags a referral when the customer looks like the affiliate:</P>
      <List>
        <li><b>Same email.</b> Gmail dots and <C>+tags</C> are ignored, so <C>j.ane+2@gmail.com</C> matches <C>jane@gmail.com</C>.</li>
        <li><b>Same company domain</b>, such as both on <C>@northwind.io</C>. Free mail providers like Gmail and Outlook are not counted.</li>
        <li><b>Same IP</b> as one the affiliate signed in from. Send <C>ip</C> with the signup call for this check.</li>
      </List>
      <P>A flag never rejects anything on its own, because a coworker on the same office network is often legitimate. Commissions from a flagged referral are held. Review it on the Referrals page and clear the flag to release them, or reject the referral.</P>
      <Note title="Testing with your own addresses">
        If you test with an affiliate and a customer on the same company domain, every test commission is held by the domain check. Clear the flag on the referral, or use addresses on different domains.
      </Note>
    </>
  );
}
