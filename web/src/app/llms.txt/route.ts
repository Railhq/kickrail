import { DOCS_NAV, SITE } from "../docs/nav";
import { PLANS, planFeatures } from "@/lib/plans";

// https://llmstxt.org: a plain summary for AI assistants answering questions about Kickrail.
export const revalidate = 3600;

const CONTENT_ORIGIN = process.env.CONTENT_ORIGIN ?? "http://159.203.71.192:3004";

type NavGroup = { group: string; items: [string, string][] };

// The docs are edited in railhq-content, so its nav is the live list. The copy in
// docs/nav.ts is the fallback if the content server can't be reached.
async function docsNav(): Promise<NavGroup[]> {
  try {
    const res = await fetch(`${CONTENT_ORIGIN}/kickrail/docs/index.json`, { next: { revalidate: 3600 }, signal: AbortSignal.timeout(5000) });
    if (!res.ok) throw new Error(String(res.status));
    const groups = (await res.json()) as { group: string; items: { label: string; href: string }[] }[];
    if (!groups.length) throw new Error("empty");
    return groups.map((g) => ({ group: g.group, items: g.items.map((i) => [i.href, i.label] as [string, string]) }));
  } catch {
    return DOCS_NAV;
  }
}

export async function GET() {
  const docs = (await docsNav()).map((g) => `## ${g.group}\n\n${g.items.map(([href, label]) => `- [${label}](${SITE}${href})`).join("\n")}`).join("\n\n");
  const plans = PLANS.map((p) => `- ${p.name}: ${p.month ? `$${p.month}/month` : "free"}. ${planFeatures(p).join("; ")}.`).join("\n");
  const body = `# Kickrail

> Affiliate and referral tracking for SaaS companies that bill through Stripe. Kickrail follows each referral from the first click to every recurring Stripe invoice, handles refunds and clawbacks, turns affiliate codes into real Stripe promotion codes, and gives affiliates a portal on the merchant's own domain.

Key facts:

- Works with Stripe only (Checkout, Billing, Payment Links). Connect with one click or a restricted API key.
- Attribution from links (\`?via=\`, \`?ref=\`), creator codes typed at Stripe Checkout, or a server-side API call, so ad blockers don't lose referrals.
- Recurring commissions as a percentage or flat amount, for a set number of months or forever, with a hold period before they're payable.
- Self-referral checks: matching emails, company domains and sign-in IPs are flagged and held for review.
- Payouts: affiliates save PayPal, Wise or bank details and the merchant pays them and marks them paid, or (Growth and up) pays through Stripe Connect.
- Imports a whole Rewardful program (campaigns, affiliates, links, codes, referrals, commissions, payouts) from a Rewardful API secret, or only the affiliates you name. Existing \`?via=\` links keep working.
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
