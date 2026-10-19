import type { Metadata } from "next";
import Link from "next/link";
import { C, H2, List, P, Title } from "../../docs/ui";
import { CONTACT_EMAIL, SUPPORT_EMAIL, UPDATED } from "@/lib/legal";

export const metadata: Metadata = {
  title: "Privacy policy",
  description: "What Kickrail collects about merchants, affiliates and referred customers, why, who it is shared with, and how to have it deleted.",
  alternates: { canonical: "/privacy" },
};

const mail = <a href={`mailto:${CONTACT_EMAIL}`} className="underline">{CONTACT_EMAIL}</a>;
const support = <a href={`mailto:${SUPPORT_EMAIL}`} className="underline">{SUPPORT_EMAIL}</a>;

export default function Privacy() {
  return (
    <>
      <Title eyebrow={`Updated ${UPDATED}`} lead="What Kickrail collects, why, who it is shared with, and how to have it deleted.">
        Privacy policy
      </Title>

      <P>
        Kickrail runs affiliate programs for software companies that bill through Stripe. This policy covers the hosted
        service at kickrail.com, the affiliate portals it serves (including portals on a merchant&apos;s own domain), and the{" "}
        <C>kr.js</C> tracking script. Kickrail&apos;s source code is public; if you run your own copy, you are responsible for it
        and this policy does not apply.
      </P>

      <H2>Who is responsible for what</H2>
      <List>
        <li>
          <strong>Merchants</strong> (the companies that run a program) and their teammates: Kickrail decides how this account
          data is used and is responsible for it.
        </li>
        <li>
          <strong>Affiliates and referred customers</strong>: Kickrail processes their data on the merchant&apos;s behalf, to run
          that merchant&apos;s program. The merchant decides what is collected and is responsible for telling affiliates and
          customers about it, including any cookie notice their own site needs. Questions about a specific program are best
          sent to that merchant first; we will help them answer.
        </li>
      </List>

      <H2>What we collect</H2>
      <P><strong>Merchant accounts.</strong></P>
      <List>
        <li>Name, email address and a hashed password.</li>
        <li>Hashed IP addresses of your last ten sign-ins, to spot account takeover. We do not keep the raw address.</li>
        <li>Program settings, campaigns, commission rules, teammates and API keys.</li>
        <li>
          Your Stripe connection: a restricted key or a Stripe Connect account id. Keys, webhook secrets and PayPal credentials are
          encrypted at rest.
        </li>
        <li>If you subscribe to a paid plan: your Stripe customer and subscription ids. Card details are handled by Stripe and never reach us.</li>
      </List>
      <P><strong>Affiliates</strong> (entered through a portal, or added or imported by the merchant).</P>
      <List>
        <li>Name, email address, hashed password and referral links or codes.</li>
        <li>Payout details you choose to give: the payout method and the address or account you enter for it.</li>
        <li>
          Tax forms (W-9 or W-8), if the merchant asks for them: legal name, business name, address, country, date of birth and
          tax id. The tax id is encrypted at rest and only its last four digits are shown.
        </li>
        <li>Clicks, referrals, commissions and payouts credited to you.</li>
      </List>
      <P><strong>Visitors and referred customers</strong> (collected by <C>kr.js</C> on the merchant&apos;s site and from the merchant&apos;s Stripe account).</P>
      <List>
        <li>When someone opens a referral link: the page URL, the referring URL, the browser&apos;s user agent, a hashed IP address and a random click id.</li>
        <li>When they sign up or pay: the email address or user id the merchant reports, their Stripe customer id, and the amounts and ids of invoices and refunds that earn or reverse commissions.</li>
      </List>

      <H2>Cookies and local storage</H2>
      <List>
        <li>On kickrail.com: <C>kr_session</C> keeps you signed in and <C>kr_program</C> remembers which program you are working in. Both are needed for the dashboard to work.</li>
        <li>
          On a merchant&apos;s site, <C>kr.js</C> stores <C>kr_ref</C> (the click id) and <C>kr_via</C> (the affiliate) as first-party cookies
          and in local storage, for the number of days the merchant sets for their program, so a later purchase is credited to the right affiliate.
        </li>
        <li>Kickrail sets no advertising cookies and runs no third-party analytics on kickrail.com.</li>
      </List>

      <H2>How we use it</H2>
      <List>
        <li>To credit referrals and calculate commissions, and to show merchants and affiliates their own numbers.</li>
        <li>To send account and program email: email verification, password resets, approvals, commission and payout notices. Merchants can switch most program emails off.</li>
        <li>To flag likely self-referrals and fraud, for example when a buyer and affiliate share an email domain.</li>
        <li>To bill paid plans and enforce plan limits.</li>
        <li>To keep the service secure and fix problems.</li>
      </List>
      <P>We do not sell personal data, use it for advertising, or use one merchant&apos;s data for another merchant.</P>

      <H2>Who we share it with</H2>
      <List>
        <li><strong>DigitalOcean</strong> hosts the application and database, in the United States.</li>
        <li><strong>Stripe</strong> handles billing for paid plans. Kickrail also reads from and writes to the merchant&apos;s own Stripe account (for example, the referring affiliate on a customer&apos;s metadata) when the merchant connects it.</li>
        <li><strong>Brevo</strong> delivers our email.</li>
        <li><strong>PayPal</strong> and <strong>Rewardful</strong> only when a merchant connects them, to send payouts or import an existing program.</li>
        <li>The merchant whose program you joined, or who you were referred to, sees your data for that program.</li>
        <li>Authorities, when the law requires it.</li>
      </List>

      <H2>How long we keep it</H2>
      <P>
        Account and program data is kept while the account is open. Raw Stripe event logs are deleted after 90 days. When a merchant
        or affiliate asks us to delete their account, we delete it within 30 days, except records we must keep for tax or legal
        reasons. Database backups roll off within a few weeks after that.
      </P>

      <H2>Your rights</H2>
      <P>
        You can ask to see, correct, export or delete your data, or object to how it is used. Merchants can export affiliates,
        referrals and commissions as CSV from the dashboard at any time. Email {mail} for anything else; we answer within 30 days.
        If you are in the EU, UK or another place with data protection law, you can also complain to your local regulator.
      </P>

      <H2>Security</H2>
      <P>
        Traffic is encrypted in transit. Passwords are hashed, IP addresses are stored only as hashes, and secrets and tax ids are
        encrypted at rest. Access to production data is limited to the people who run the service.
      </P>

      <H2>Children</H2>
      <P>Kickrail is a business tool and is not meant for anyone under 16.</P>

      <H2>Changes</H2>
      <P>
        If we change this policy in a way that matters, we will email merchants before it takes effect. The date at the top shows the
        latest version. See also the <Link href="/terms" className="underline">terms of service</Link>.
      </P>

      <H2>Contact</H2>
      <P>Questions about these terms or your data: {mail}. Help with your account: {support}.</P>
    </>
  );
}
