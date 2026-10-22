import { addDomain, connectPayPal, disconnectPayPal, makePrimaryDomain, removeDomain, saveBranding, saveEmailSettings, updateSettings, verifyDomain } from "@/app/actions";
import { ActionForm, Submit } from "@/components/ActionForm";
import { CopyButton } from "@/components/CopyButton";
import { Badge, Card, Code, Field, Notice } from "@/components/ui";
import { api, siteUrl } from "@/lib/backend";
import { date } from "@/lib/format";
import type { Import, Merchant } from "@/lib/types";
import { RewardfulImport } from "./RewardfulImport";
import { ConnectStripeButton, ConnectStripeForm, DisconnectStripe, RotateSecret } from "./StripeForms";

// Same list as the backend's fx.DISPLAY_CURRENCIES.
const DISPLAY_CURRENCIES = ["usd", "eur", "gbp", "cad", "aud", "inr", "jpy", "sgd", "chf", "nzd", "sek", "brl", "mxn"];

export const metadata = { title: "Settings" };

const EMAIL_KINDS: [string, string][] = [
  ["welcome", "Welcome email when someone joins"],
  ["approved", "Approval email when you approve a pending affiliate"],
  ["commission", "Email the affiliate for every new commission"],
  ["payout", "Email the affiliate when a payout is sent"],
  ["new_affiliate", "Email your team when someone applies"],
];

const PERMS = [
  ["Customers", "Write"],
  ["Charges", "Read"],
  ["Invoices", "Read"],
  ["Checkout Sessions", "Read"],
  ["Coupons", "Read"],
  ["Promotion Codes", "Write"],
  ["Webhook Endpoints", "Write"],
];

export default async function SettingsPage() {
  const [m, site, imp] = await Promise.all([api<Merchant>("/merchant"), siteUrl(), api<{ import: Import | null }>("/merchant/import")]);
  const param = m.settings.param_names[0];
  const serverCall = `// After a user signs up, on your server:
await fetch("${site}/api/v1/referrals", {
  method: "POST",
  headers: {
    "Authorization": "Bearer " + process.env.KICKRAIL_SECRET_KEY,
    "Content-Type": "application/json",
  },
  body: JSON.stringify({
    referral: req.cookies.kr_ref,    // set by the script on your domain
    email: user.email,
    user_id: user.id,
    stripe_customer_id: user.stripeCustomerId, // if you already have it
    ip: req.ip,                      // used for self-referral checks
  }),
});`;
  const checkout = `// On your server:
stripe.checkout.sessions.create({
  client_reference_id: req.cookies.kr_ref,
  // ...
});
stripe.customers.create({ email, metadata: { kr_ref: req.cookies.kr_ref } });`;
  const keyForm = (
    <>
      <p className="text-sm text-muted">
        In Stripe, go to Developers → API keys → <b>Create restricted key</b> and grant the permissions below. Kickrail encrypts the key and creates its own webhook endpoint, so there is nothing else to configure.
      </p>
      <ul className="my-3 grid grid-cols-2 gap-x-6 gap-y-1 text-sm sm:grid-cols-3">
        {PERMS.map(([n, p]) => <li key={n}>{n}: <span className="text-muted">{p}</span></li>)}
      </ul>
      <ConnectStripeForm connected={!!m.stripe} />
    </>
  );
  const proxied = `<script async src="/kr/kr.js?k=${m.public_key}&api=/kr"></script>`;
  return (
    <div className="space-y-6">
      <h1 className="page-title">Settings</h1>

      <Card title="Stripe" className="scroll-mt-6" id="stripe" actions={m.stripe && <Badge tone={m.stripe.livemode ? "green" : "amber"}>{m.stripe.livemode ? "live mode" : "test mode"}</Badge>}>
        {m.stripe && (
          <div className="mb-4 flex flex-wrap items-center justify-between gap-3 rounded-xl border border-line bg-sunk/50 p-3 text-sm">
            <span>Connected to <b>{m.stripe.account_name}</b> <span className="font-mono text-xs text-muted">{m.stripe.account_id}</span> since {date(m.stripe.connected_at)}</span>
            <DisconnectStripe />
          </div>
        )}
        {m.stripe_oauth ? (
          <>
            <p className="text-sm text-muted">Approve Kickrail on stripe.com and you&apos;re done. Kickrail sees your payments as they happen and creates promotion codes for creator codes. Nothing to configure in Stripe.</p>
            <div className="mt-3"><ConnectStripeButton connected={!!m.stripe} /></div>
            <details className="mt-4 text-sm">
              <summary className="cursor-pointer text-muted">Or connect with a restricted key</summary>
              <div className="mt-3">{keyForm}</div>
            </details>
          </>
        ) : keyForm}
      </Card>

      <Card title="Install" className="scroll-mt-6" actions={<a className="link text-sm" href="/docs/tracking">Install guide</a>}>
        <div id="install" className="space-y-5 text-sm">
          <div>
            <p className="font-medium">1. Connect Stripe {m.stripe && <Badge tone="green">done</Badge>}</p>
            <p className="mt-1 text-muted">{m.stripe ? <>Connected to <b>{m.stripe.account_name}</b>. Payments are picked up automatically.</> : <>So Kickrail can see payments. <a className="link" href="#stripe">Connect above</a>.</>}</p>
          </div>
          <div>
            <p className="font-medium">2. Add the script to every page of your marketing site and app</p>
            <p className="mt-1 text-muted">
              It records clicks on links like <code>{m.website}/?{param}=jane</code> and keeps the referral in a first-party cookie. When a referred visitor submits a form with an email in it, like your signup form, the script reports that email, and their first payment in Stripe earns the commission. Stripe Payment Links, pricing tables and buy buttons get the referral too.
            </p>
            <div className="mt-2 flex items-start gap-2"><div className="min-w-0 flex-1"><Code>{m.snippet}</Code></div><CopyButton text={m.snippet} /></div>
            <p className="mt-2 text-xs text-muted">Signups caught this way only count Stripe customers created after the signup, so an existing customer who clicks a link and logs in isn&apos;t credited. Add <code>data-kickrail-ignore</code> to a form to skip it.</p>
          </div>
          <details>
            <summary className="cursor-pointer font-medium">3. Advanced (optional): pass the referral yourself</summary>
            <div className="mt-3 space-y-5">
              <div>
                <p className="text-muted">Pass <code>kr_ref</code> to Stripe when you create the checkout or customer. This always wins over the automatic email match.</p>
                <div className="mt-2"><Code>{checkout}</Code></div>
              </div>
              <div>
                <p className="text-muted">Or report signups from your server. Ad blockers and Safari can&apos;t interfere with a server-to-server call, and it works when signup isn&apos;t a plain form.</p>
                <div className="mt-2"><Code>{serverCall}</Code></div>
              </div>
              <div>
                <p className="text-muted">Serve tracking from your own domain: proxy <code>/kr/*</code> on your domain to <code>{site}/api/*</code> and load the script with an <code>api</code> parameter. Requests then look first-party to the browser.</p>
                <div className="mt-2"><Code>{proxied}</Code></div>
              </div>
            </div>
          </details>
        </div>
      </Card>

      <Card title="Server API key" actions={<RotateSecret />}>
        <p className="text-sm text-muted">Used as <code>Authorization: Bearer …</code> for the <a className="link" href="/dashboard/developers">REST API</a>. Current key: <code className="font-mono">{m.secret_key_hint}</code>. Rolling it stops the old key immediately. The same key lets a coding agent set Kickrail up for you: see <a className="link" href="/docs/mcp">MCP setup</a>.</p>
      </Card>

      <Card title="Program">
        <ActionForm action={updateSettings} className="grid gap-4 sm:grid-cols-2">
          <Field label="Name"><input className="input" name="name" defaultValue={m.name} required /></Field>
          <Field label="Website"><input className="input" name="website" type="url" defaultValue={m.website} required /></Field>
          <Field label="Cookie window (days)" hint="How long a click stays attributable before signup."><input className="input" name="cookie_days" type="number" min="1" max="365" defaultValue={m.settings.cookie_days} /></Field>
          <Field label="Link parameters" hint="Comma separated. The first is used in affiliate links."><input className="input font-mono" name="param_names" defaultValue={m.settings.param_names.join(", ")} /></Field>
          <Field label="Display currency" hint="Totals that mix currencies are shown as one approximate amount in this currency, at today's ECB rate. Commissions and payouts keep the sale's currency.">
            <select className="input" name="display_currency" defaultValue={m.settings.display_currency ?? "usd"}>
              {DISPLAY_CURRENCIES.map((c) => <option key={c} value={c}>{c.toUpperCase()}</option>)}
            </select>
          </Field>
          <div className="space-y-2 sm:col-span-2">
            <label className="flex items-center gap-2 text-sm">
              <input type="checkbox" name="auto_approve" defaultChecked={m.settings.auto_approve} /> Approve new affiliates automatically
            </label>
            <label className="flex items-center gap-2 text-sm">
              <input type="checkbox" name="affiliate_links" defaultChecked={m.settings.affiliate_links} /> Let affiliates create extra links and pick landing pages on your site
            </label>
            <label className="flex items-center gap-2 text-sm">
              <input type="checkbox" name="require_tax_form" defaultChecked={m.settings.require_tax_form} /> Require a signed W-9 or W-8 before an affiliate can be paid
            </label>
          </div>
          <fieldset className="space-y-2 sm:col-span-2">
            <legend className="mb-1 text-sm font-medium">When two affiliates refer the same person</legend>
            <label className="flex items-start gap-2 text-sm">
              <input type="radio" name="attribution" value="first" className="mt-1" defaultChecked={m.settings.attribution !== "last"} />
              <span><b>First touch.</b> <span className="text-muted">The first affiliate to bring someone in keeps them.</span></span>
            </label>
            <label className="flex items-start gap-2 text-sm">
              <input type="radio" name="attribution" value="last" className="mt-1" defaultChecked={m.settings.attribution === "last"} />
              <span><b>Last touch.</b> <span className="text-muted">A newer link click or code moves them to that affiliate, up to their first payment. After that they stay put.</span></span>
            </label>
          </fieldset>
          <div className="sm:col-span-2"><Submit>Save</Submit></div>
        </ActionForm>
      </Card>

      <Card title="Branding">
        <p className="mb-4 text-sm text-muted">Shown on your join page, in the affiliate portal and in every email Kickrail sends for you.</p>
        <ActionForm action={saveBranding} className="grid gap-4 sm:grid-cols-2">
          <Field label="Logo URL" hint="A square PNG or SVG works best."><input className="input" name="logo_url" type="url" defaultValue={m.branding.logo_url ?? ""} placeholder="https://…/logo.png" /></Field>
          <Field label="Brand colour">
            <input className="input font-mono" name="color" defaultValue={m.branding.color ?? ""} placeholder="#0f5e4b" pattern="#[0-9a-fA-F]{6}" />
          </Field>
          <Field label="Join page headline"><input className="input" name="headline" maxLength={120} defaultValue={m.branding.headline ?? ""} placeholder={`Partner with ${m.name}`} /></Field>
          <Field label="Terms URL"><input className="input" name="terms_url" type="url" defaultValue={m.branding.terms_url ?? ""} /></Field>
          <div className="sm:col-span-2"><Field label="Join page description"><textarea className="input min-h-20" name="description" maxLength={2000} defaultValue={m.branding.description ?? ""} /></Field></div>
          <div className="sm:col-span-2"><Field label="Welcome message" hint="Added to the approval email and shown at the top of an approved affiliate's portal."><textarea className="input min-h-16" name="welcome_message" maxLength={1000} defaultValue={m.branding.welcome_message ?? ""} /></Field></div>
          <Field label="Reply-to email" hint="Where affiliate replies go. Defaults to the workspace owner."><input className="input" name="reply_to" type="email" defaultValue={m.branding.reply_to ?? ""} /></Field>
          <div className="sm:col-span-2"><Submit>Save branding</Submit></div>
        </ActionForm>
      </Card>

      <Card title="Portal domains" actions={<span className="text-xs text-muted">{m.portal_domains.length} of {m.domain_limit} on {m.plan.name}</span>}>
        <p className="text-sm text-muted">
          Serve your join page and affiliate portal from your own hostname, like <code>partners.{m.website.replace(/^https?:\/\//, "").replace(/^www\./, "").replace(/\/.*/, "")}</code>. Add a CNAME record pointing to <code className="font-mono">{m.cname_target}</code>, then verify. We get the HTTPS certificate for you. Every verified domain serves the portal; links and emails use the primary one.
        </p>
        <p className="mt-2 text-sm">Join link: <a className="link font-mono text-xs" href={m.join_url}>{m.join_url}</a></p>
        {m.portal_domains.length > 0 && (
          <div className="mt-4 space-y-2">
            {m.portal_domains.map((d) => {
              const live = d.verified && d.https !== false;
              return (
                <div key={d.host} className="flex flex-wrap items-center gap-3 rounded-xl border border-line bg-sunk/50 p-3 text-sm">
                  <span className="font-mono">{d.host}</span>
                  {live ? <Badge tone="green">live</Badge> : <Badge tone="amber">{d.verified ? "waiting for HTTPS" : "not verified"}</Badge>}
                  {d.primary && <Badge>primary</Badge>}
                  {d.over_limit && <Badge tone="amber">over plan limit</Badge>}
                  {!d.verified && <span className="text-muted">CNAME → {m.cname_target}</span>}
                  {!d.verified && d.detail && <span className="text-amber-800">{d.detail}</span>}
                  {d.verified && d.https === false && <span className="text-amber-800">{d.https_detail}</span>}
                  <span className="ml-auto flex gap-2">
                    {(!d.verified || d.https === false) && <ActionForm action={verifyDomain.bind(null, d.host)}><Submit variant="secondary">{d.verified ? "Check again" : "Check DNS"}</Submit></ActionForm>}
                    {!d.primary && d.verified && <form action={makePrimaryDomain.bind(null, d.host)}><button className="btn btn-secondary">Make primary</button></form>}
                    <form action={removeDomain.bind(null, d.host)}><button className="btn btn-danger">Remove</button></form>
                  </span>
                </div>
              );
            })}
          </div>
        )}
        {m.portal_domains.some((d) => d.over_limit) && (
          <p className="mt-3 text-sm text-amber-800">Domains past your plan&apos;s limit keep working. To add another, remove one or <a className="link" href="/dashboard/billing">upgrade</a>.</p>
        )}
        {m.portal_domains.length < m.domain_limit ? (
          <ActionForm action={addDomain} className="mt-4 flex flex-wrap gap-2">
            <input className="input max-w-sm font-mono" name="host" placeholder="partners.example.com" required />
            <Submit variant="secondary">Add domain</Submit>
          </ActionForm>
        ) : (
          m.domain_limit === 0 && <p className="mt-4 text-sm">Custom domains start on the Starter plan. <a className="link" href="/dashboard/billing">See plans</a></p>
        )}
      </Card>

      <Card title="Emails to affiliates">
        <p className="mb-4 text-sm text-muted">Sent from your program name, with your branding. Every email is listed under <a className="link" href="/dashboard/emails">Emails</a>.</p>
        <ActionForm action={saveEmailSettings} className="space-y-2">
          {EMAIL_KINDS.map(([k, label]) => (
            <label key={k} className="flex items-center gap-2 text-sm">
              <input type="hidden" name="kinds" value={k} />
              <input type="checkbox" name={`email_${k}`} defaultChecked={m.settings.emails[k] ?? true} /> {label}
            </label>
          ))}
          <div className="pt-2"><Submit variant="secondary">Save</Submit></div>
        </ActionForm>
      </Card>

      <Card title="PayPal payouts" actions={m.paypal && <Badge tone={m.paypal.mode === "live" ? "green" : "amber"}>{m.paypal.mode}</Badge>}>
        {m.paypal ? (
          <div className="flex flex-wrap items-center justify-between gap-3 rounded-xl border border-line bg-sunk/50 p-3 text-sm">
            <span>Connected app <span className="font-mono text-xs">{m.paypal.client_id_hint}</span> since {date(m.paypal.connected_at)}</span>
            <form action={disconnectPayPal}><button className="btn btn-danger">Disconnect</button></form>
          </div>
        ) : (
          <>
            <p className="text-sm text-muted">
              Pay affiliates who saved a PayPal email in one batch from the Payouts page. Create a REST app at developer.paypal.com with Payouts enabled and paste its credentials. The secret is encrypted at rest.
            </p>
            {m.stripe?.livemode === false && <div className="mt-3"><Notice>Use sandbox credentials while you test.</Notice></div>}
            <ActionForm action={connectPayPal} className="mt-4 grid gap-3 sm:grid-cols-[1fr_1fr_8rem_auto]">
              <input className="input font-mono text-xs" name="client_id" placeholder="Client ID" required aria-label="Client ID" />
              <input className="input font-mono text-xs" name="secret" type="password" placeholder="Secret" required aria-label="Secret" />
              <select className="input" name="mode" defaultValue="sandbox" aria-label="Mode">
                <option value="sandbox">Sandbox</option>
                <option value="live">Live</option>
              </select>
              <Submit variant="secondary">Connect</Submit>
            </ActionForm>
          </>
        )}
      </Card>

      <Card title="Import from Rewardful">
        <RewardfulImport initial={imp.import} />
      </Card>
    </div>
  );
}
