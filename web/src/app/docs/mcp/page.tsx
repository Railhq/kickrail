import type { Metadata } from "next";
import Link from "next/link";
import { SITE } from "../nav";
import { C, H2, List, Note, P, Snippet, Title } from "../ui";

export const metadata: Metadata = { title: "Set up with an AI agent (MCP)" };

export default function Mcp() {
  return (
    <>
      <Title eyebrow="Developers" lead="Kickrail is an MCP server. Point Claude Code, Cursor or another coding agent at it and the agent can install tracking in your codebase, check it works on your live site, set your commissions and import from Rewardful, while you only click Approve on Stripe.">
        Set up with an AI agent (MCP)
      </Title>

      <H2>Connect your agent</H2>
      <P>Create a program in the dashboard first, then copy the server key from Settings → Server API key (it starts with <C>sk_kr_</C>). The MCP endpoint is <C>{`${SITE}/api/mcp`}</C> over Streamable HTTP.</P>
      <Snippet label="Claude Code">{`claude mcp add --transport http kickrail ${SITE}/api/mcp \\
  --header "Authorization: Bearer sk_kr_..."`}</Snippet>
      <Snippet label="Cursor (.cursor/mcp.json)">{`{
  "mcpServers": {
    "kickrail": {
      "url": "${SITE}/api/mcp",
      "headers": { "Authorization": "Bearer \${env:KICKRAIL_SECRET_KEY}" }
    }
  }
}`}</Snippet>
      <P>Then ask it something like:</P>
      <Snippet label="Prompt">{`Set up Kickrail affiliate tracking in this app. Use the kickrail MCP:
check setup_status, install the script, report signups from our
signup handler, and verify it on the live site.`}</Snippet>
      <Note>The key is your program&apos;s server key, so the agent can do what the REST API can. Keep it out of committed files. Rolling the key in Settings disconnects the agent until you update it.</Note>

      <H2>What the agent can do</H2>
      <List>
        <li><C>setup_status</C>: what&apos;s done (Stripe, script, test click, affiliates) and the next step.</li>
        <li><C>connect_stripe</C>: a link for you to open. Stripe approval is always yours to click.</li>
        <li><C>get_install_instructions</C>: the script tag and where it goes for Next.js, React, plain HTML, WordPress, Webflow, Framer or Shopify, plus the <Link className="link" href="/docs/server">server signup call</Link>.</li>
        <li><C>verify_install</C>: fetches your live site, checks for the script, reports whether browsers have loaded it, and gives a test link.</li>
        <li><C>list_campaigns</C>, <C>create_campaign</C>, <C>update_campaign</C>, <C>update_program</C>: commission rate, duration, hold period, cookie length.</li>
        <li><C>add_affiliate</C>, <C>list_affiliates</C>, <C>list_referrals</C>, <C>list_commissions</C>: Growth plan or trial, like the API.</li>
        <li><C>list_portal_domains</C>, <C>add_portal_domain</C>, <C>check_portal_domain</C>: serve the join page from your own subdomain. The agent gives you the CNAME record (or adds it, if it can reach your DNS provider) and checks it until it&apos;s live.</li>
        <li><C>start_rewardful_import</C>, <C>import_status</C>: the same <Link className="link" href="/docs/switching">Rewardful import</Link> as the dashboard, for the whole program or only the affiliates in <C>only</C>. The Rewardful secret is used once and never stored.</li>
      </List>
      <P>Payouts aren&apos;t exposed to agents. Paying affiliates stays in the dashboard.</P>
    </>
  );
}
