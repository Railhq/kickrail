import type { Metadata } from "next";
import Link from "next/link";
import { SITE } from "../nav";
import { C, Fields, H2, List, Note, P, Title } from "../ui";

export const metadata: Metadata = { title: "Affiliate portal and domains" };

export default function Portal() {
  return (
    <>
      <Title eyebrow="Running a program" lead="Affiliates join, get their links and codes, and check their earnings in a portal branded for your program. It runs on Kickrail's domain out of the box, or on your own.">
        Affiliate portal and domains
      </Title>

      <H2>The join page</H2>
      <P>Every program has a public join page at <C>{SITE}/join/your-program</C>. Share it on your site, in your footer, or in an email to customers. People who join there go on your default campaign; a campaign with a public join page also has its own page at <C>{SITE}/join/your-program/page-name</C> (on a custom domain, <C>partners.yourapp.com/join/page-name</C>). See <Link className="link" href="/docs/commissions">Campaigns</Link>. Settings → Branding sets the logo, brand colour, headline, description, terms link, welcome message and reply-to address used on it and in every email Kickrail sends for you.</P>
      <P>New affiliates are approved automatically unless you turn that off in Settings → Program; then they wait in Affiliates for you to approve or reject them. You can also invite affiliates yourself, or create them over the API.</P>

      <H2>What affiliates see</H2>
      <List>
        <li>Their main link, extra links with their own landing pages, and their creator codes.</li>
        <li>Clicks, signups and customers, and a &quot;test my link&quot; button that confirms a click landed.</li>
        <li>Every commission: pending money with the date its hold ends, paid amounts, and refunds.</li>
        <li>Where they want to be paid (PayPal, Wise, bank, or other), and a W-9 or W-8 form if you ask for one.</li>
      </List>
      <P>Affiliates sign in with their email and a password. One person can be an affiliate of several programs.</P>

      <H2>Use your own domain</H2>
      <P>On Starter and up you can put the portal on a hostname you own, such as <C>partners.yourapp.com</C>. The root of that hostname shows your join page, and sign-in and the portal work on it too.</P>
      <List ordered>
        <li>In Settings → Portal domains, add the hostname.</li>
        <li>At your DNS provider, add a <b>CNAME</b> record from that hostname to <C>portals.kickrail.com</C>.</li>
        <li>Click <b>Check DNS</b>. Once the record is found, Kickrail issues an HTTPS certificate the first time the domain is visited, usually within a minute.</li>
      </List>
      <Fields
        head={["Badge", "Meaning", ""]}
        rows={[
          ["not verified", "the CNAME isn't visible yet", "DNS changes can take a few minutes to an hour. Check again later."],
          ["waiting for HTTPS", "verified, no certificate yet", "Open the domain once in a browser to request it."],
          ["live", "working", "Affiliates can join and sign in here."],
          ["primary", "the main domain", "Affiliate links and emails use the primary domain once it is verified. The first domain you add is primary."],
        ]}
      />
      <Note title="Cloudflare and other proxies">
        Set the record to <b>DNS only</b> (grey cloud) so the certificate can be issued. A root domain such as <C>yourapp.com</C> can&apos;t be a CNAME; use a subdomain.
      </Note>
      <P>Starter includes 1 domain, Growth 3 and Scale 10, for example one per brand or market. If you move to a smaller plan, domains you already have keep working; you just can&apos;t add more.</P>

      <H2>Your team</H2>
      <P>Invite teammates from Team. Everyone on a team can see and manage the program; only the owner manages billing. Free includes 1 seat, Starter 3, and Growth and Scale have no limit. One login can run several programs, each with its own Stripe account, affiliates and keys; switch between them from the sidebar.</P>
    </>
  );
}
