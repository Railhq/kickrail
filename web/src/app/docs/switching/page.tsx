import type { Metadata } from "next";
import Link from "next/link";
import { C, Fields, H2, List, Note, P, Title } from "../ui";

export const metadata: Metadata = { title: "Switching from Rewardful" };

export default function Switching() {
  return (
    <>
      <Title eyebrow="Get started" lead="Bring your program over from Rewardful in one step, without asking affiliates to change their links. And if you ever leave Kickrail, everything comes out as CSV.">
        Switching from Rewardful
      </Title>

      <H2>Import from Rewardful</H2>
      <List ordered>
        <li>In Rewardful, open Company settings and copy your <b>API secret</b>.</li>
        <li>In Kickrail, go to Settings → <b>Import from Rewardful</b>, paste it and start the import.</li>
        <li>Leave the page open or come back later. Large programs take a few minutes: Rewardful lets Kickrail read up to about 8,000 records a minute.</li>
      </List>
      <P>The secret is used for that run only. Kickrail doesn&apos;t store it, log it or show it again.</P>

      <H2>What moves over</H2>
      <Fields
        head={["Rewardful", "In Kickrail", "Notes"]}
        rows={[
          ["Campaigns", "Campaigns", <>Percent or flat rate, the month limit, days until due (the hold), minimum payout, Stripe coupon and link URL. Your default campaign becomes Kickrail&apos;s default.</>],
          ["Affiliates", "Affiliates", <>Name, email, campaign, PayPal email. Active affiliates are approved; disabled or suspicious ones are rejected.</>],
          ["Links", "Links", <>Same tokens. <C>?via=</C> is one of Kickrail&apos;s link params, so every link already shared keeps working.</>],
          ["Coupons", "Codes", <>Same codes, tied to the same Stripe promotion codes, so they keep crediting at checkout.</>],
          ["Leads and conversions", "Referrals", <>With the customer&apos;s email and Stripe customer, so renewals keep crediting the same affiliate. Visitors who never signed up aren&apos;t copied.</>],
          ["Commissions", "Commissions", <>Amount, sale, due date and state. Unpaid ones stay owed and show on the Payouts page when due.</>],
          ["Paid payouts", "Payouts", <>As paid history. Payouts not yet paid in Rewardful aren&apos;t copied: their commissions are owed in Kickrail instead.</>],
        ]}
      />

      <H2>Importing only some affiliates</H2>
      <P>
        Rewardful can enroll every customer as an affiliate, so a program can hold thousands of affiliates who never promote it. To bring over only your partners, list them under <b>Only these
        affiliates</b>, by email or Rewardful affiliate id, one per line. Kickrail then copies just those affiliates, the campaigns they belong to, and their links, codes, referrals, commissions and
        paid payouts. Names it can&apos;t find in Rewardful are listed in the import&apos;s notes. Leave the box empty to import everything.
      </P>

      <H2>Running it again</H2>
      <P>
        Every imported record remembers its Rewardful id, so a second run updates what&apos;s there instead of adding copies. Run it once more right before you remove Rewardful&apos;s script to pick up
        the latest signups. A commission you&apos;ve already paid through Kickrail is never changed by a later import.
      </P>
      <P>Someone who was already an affiliate in your Kickrail program keeps their account, and their Rewardful links and codes are added to it. A customer Kickrail already tracked keeps the affiliate Kickrail credited.</P>

      <H2>Affiliate logins</H2>
      <P>
        Passwords can&apos;t be moved out of Rewardful. Imported affiliates get a Kickrail account with no password. Tick <b>Email imported affiliates a link to set their password</b> when you&apos;re
        ready; each person gets that email once, with their link and code. It&apos;s off by default so you can tell them about the move first. Nothing else is emailed and no webhooks fire during an import.
      </P>

      <H2>After the import</H2>
      <List ordered>
        <li><Link className="link" href="/docs/tracking">Install Kickrail&apos;s tracking</Link> in place of Rewardful&apos;s script, and <Link className="link" href="/docs/server">report signups</Link> the same way you did.</li>
        <li>Connect Stripe in Settings so new payments and renewals earn commissions.</li>
        <li>Turn off Rewardful&apos;s Stripe integration, so the same payment doesn&apos;t earn a commission in both tools.</li>
        <li>Pay affiliates from one place only. If you pay something in Rewardful after importing, run the import again and it&apos;s marked paid here too.</li>
      </List>
      <Note title="Plan limits">
        The Free plan has one campaign, so on Free every affiliate joins your default campaign and the import lists which campaigns were folded in. Stripe coupons on a campaign need Starter or higher.
        Rewardful&apos;s &quot;maximum number of commissions&quot; above one isn&apos;t a Kickrail setting; the month limit still applies.
      </Note>

      <H2>Getting your data out</H2>
      <P>
        The Affiliates, Referrals and Commissions pages each have an <b>Export CSV</b> button with everything on them: links, codes, customer emails, Stripe customer ids, amounts and dates. On Growth and up,
        the same data is in the <Link className="link" href="/docs/api">API</Link>.
      </P>
    </>
  );
}
