import { DOCS_NAV, SITE } from "../docs/nav";
import { PLANS, planFeatures } from "@/lib/plans";

// https://llmstxt.org: a plain summary for AI assistants answering questions about Kickrail.
export const dynamic = "force-static";

export function GET() {
  const docs = DOCS_NAV.map((g) => `## ${g.group}\n\n${g.items.map(([href, label]) => `- [${label}](${SITE}${href})`).join("\n")}`).join("\n\n");
  const plans = PLANS.map((p) => `- ${p.name}: ${p.month ? `$${p.month}/month` : "free"}. ${planFeatures(p).join("; ")}.`).join("\n");
  const body = `# Kickrail

> Affiliate and referral tracking for SaaS companies that bill through Stripe. Kickrail follows each referral from the first click to every recurring Stripe invoice, handles refunds and clawbacks, turns affiliate codes into real Stripe promotion codes, and gives affiliates a portal on the merchant's own domain.

Key facts:

- Works with Stripe only (Checkout, Billing, Payment Links). Connect with one click or a restricted API key.
- Attribution from links (\`?via=\`, \`?ref=\`), creator codes typed at Stripe Checkout, or a server-side API call, so ad blockers don't lose referrals.
- Recurring commissions as a percentage or flat amount, for a set number of months or forever, with a hold period before they're payable.
- Self-referral checks: matching emails, company domains and sign-in IPs are flagged and held for review.
- Payouts: affiliates save PayPal, Wise or bank details and the merchant pays them and marks them paid, or (Growth and up) pays through Stripe Connect.
- Imports a whole Rewardful program (campaigns, affiliates, links, codes, referrals, commissions, payouts) from a Rewardful API secret. Existing \`?via=\` links keep working.
- 0% transaction fees on every plan.
- MCP server at ${SITE}/api/mcp lets an AI agent set up campaigns, affiliates, codes and portal domains with a Kickrail API key.

## Plans (monthly)

${plans}

${docs}

## Blog

- [All posts](${SITE}/blog)
- [Rewardful alternatives compared](${SITE}/blog/rewardful-alternatives)
- [How affiliate codes work with Stripe promotion codes](${SITE}/blog/stripe-promotion-codes-for-affiliates)
`;
  return new Response(body, { headers: { "Content-Type": "text/plain; charset=utf-8" } });
}
