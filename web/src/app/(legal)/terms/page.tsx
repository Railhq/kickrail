import type { Metadata } from "next";
import Link from "next/link";
import { H2, List, P, Title } from "../../docs/ui";
import { CONTACT_EMAIL, UPDATED } from "@/lib/legal";

export const metadata: Metadata = {
  title: "Terms of service",
  description: "The terms for using Kickrail's hosted affiliate tracking service, for merchants and affiliates.",
  alternates: { canonical: "/terms" },
};

const mail = <a href={`mailto:${CONTACT_EMAIL}`} className="underline">{CONTACT_EMAIL}</a>;

export default function Terms() {
  return (
    <>
      <Title eyebrow={`Updated ${UPDATED}`} lead="The rules for using Kickrail's hosted service, for the companies that run programs and the affiliates who join them.">
        Terms of service
      </Title>

      <P>
        By creating an account on kickrail.com or joining a program through a Kickrail portal, you agree to these terms. If you sign
        up for a company, you confirm you can agree for it. Kickrail&apos;s source code is published under the AGPL-3.0 license; that
        license covers the code, and these terms cover the hosted service.
      </P>

      <H2>The service</H2>
      <P>
        Kickrail tracks referral links and codes, attributes Stripe sign-ups and payments to affiliates, calculates commissions, and
        gives merchants and affiliates a dashboard, portal, API and webhooks. Kickrail is not a bank or payment processor and never
        holds anyone&apos;s money. Payouts are sent by the merchant, either by hand or through a payment provider the merchant connects.
      </P>

      <H2>Accounts</H2>
      <List>
        <li>Give accurate information and keep your password and API keys safe. You are responsible for what happens under your account.</li>
        <li>Tell us at {mail} if you think someone else has access to your account.</li>
        <li>You must be at least 16, and old enough to form a contract where you live.</li>
      </List>

      <H2>Plans and billing</H2>
      <List>
        <li>The Free plan costs nothing. Paid plans are billed monthly or yearly in advance through Stripe, per program, at the prices on the <Link href="/#pricing" className="underline">pricing page</Link>. Kickrail takes no percentage of your revenue or your affiliates&apos; commissions.</li>
        <li>New programs get a 14-day trial of the Growth plan without a card. If you don&apos;t subscribe, the program moves to the Free plan when the trial ends.</li>
        <li>You can cancel at any time from the billing page. The plan stays active until the end of the period you paid for, then moves to Free. We don&apos;t refund partial periods.</li>
        <li>Each plan has limits, such as tracked affiliate revenue per month, custom domains and teammates. Going over a limit never stops tracking. If a program stays over its revenue limit, we will tell you and ask you to upgrade. Moving to a smaller plan keeps what you already have, but you can&apos;t add more beyond its limits.</li>
        <li>We will give at least 30 days&apos; notice by email before changing the price of a plan you pay for.</li>
      </List>

      <H2>Merchants&apos; responsibilities</H2>
      <List>
        <li>Your affiliate program is yours. You set its terms, decide who to approve, and pay the commissions you owe. Kickrail is not a party to the agreement between you and your affiliates.</li>
        <li>Check commissions before you pay them. Attribution depends on cookies, browsers, your integration and Stripe data, so it can miss or misattribute a sale. Kickrail is not liable for commissions paid or unpaid.</li>
        <li>You are responsible for taxes and tax reporting on payments to your affiliates.</li>
        <li>You must have a lawful basis to track visitors and share customer data with Kickrail, and give any notice or consent prompt your own site needs. Our <Link href="/privacy" className="underline">privacy policy</Link> describes what <code>kr.js</code> stores.</li>
      </List>

      <H2>Affiliates</H2>
      <P>
        When you join a program you deal with that merchant: they approve you, set your commission and pay you. Kickrail only provides
        the tools. Questions about a commission or payout go to the merchant first.
      </P>

      <H2>Acceptable use</H2>
      <P>You may not use Kickrail to:</P>
      <List>
        <li>Break the law, or promote products or services that are illegal where they are sold.</li>
        <li>Send spam, or create fake clicks, sign-ups, referrals or self-referrals to earn commissions.</li>
        <li>Collect data about people without the right to do so.</li>
        <li>Get around plan limits, probe or overload the service, or access accounts and data that aren&apos;t yours.</li>
      </List>
      <P>We may suspend an account that does any of this. Where we can, we will tell you first and give you a chance to fix it.</P>

      <H2>Your data</H2>
      <P>
        Data you put into Kickrail stays yours. You give us permission to store and process it only to provide the service, as described
        in the <Link href="/privacy" className="underline">privacy policy</Link>. You can export it from the dashboard or the API at any time.
      </P>

      <H2>Availability</H2>
      <P>
        We work to keep Kickrail running and your data safe, but we don&apos;t promise it will be uninterrupted or error-free, and there
        is no uptime guarantee. We may change or remove features; if we remove something you rely on, we will tell you in advance.
      </P>

      <H2>Ending your account</H2>
      <P>
        You can stop using Kickrail at any time and ask us to delete your account. We may close an account that breaks these terms,
        or end the hosted service with at least 60 days&apos; notice. Either way, you can export your data before it is deleted.
      </P>

      <H2>Disclaimers and liability</H2>
      <P>
        Kickrail is provided &quot;as is&quot;, without warranties of any kind, as far as the law allows. Kickrail is not liable for
        indirect or consequential losses, such as lost profits, lost data or commissions paid in error. Our total liability for any
        claim is limited to the amount you paid Kickrail in the 12 months before it arose, or US$100 if that is more.
      </P>

      <H2>Changes to these terms</H2>
      <P>
        We may update these terms. If a change matters, we will email account owners at least 14 days before it takes effect.
        Continuing to use Kickrail after that means you accept the new terms.
      </P>

      <H2>Governing law</H2>
      <P>These terms are governed by the laws of the United States of America.</P>

      <H2>Contact</H2>
      <P>{mail}</P>
    </>
  );
}
