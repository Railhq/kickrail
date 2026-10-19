"use server";

import { revalidatePath } from "next/cache";
import { redirect } from "next/navigation";
import { api, ApiError, siteUrl } from "@/lib/backend";
import { clearSession, setProgram, setSession } from "@/lib/session";

export type State = { error?: string; ok?: string; secret?: string } | null;

const str = (f: FormData, k: string) => (f.get(k) as string | null)?.trim() ?? "";
const num = (f: FormData, k: string) => (str(f, k) === "" ? undefined : Number(str(f, k)));
const cents = (f: FormData, k: string) => (str(f, k) === "" ? undefined : Math.round(Number(str(f, k)) * 100));

/** Run a backend call; turn backend errors into form state. Redirects happen after this returns. */
async function attempt<T>(fn: () => Promise<T>): Promise<{ value?: T; error?: string }> {
  try {
    return { value: await fn() };
  } catch (e) {
    if (e instanceof ApiError) return { error: e.message };
    throw e;
  }
}

function safeNext(next: string, fallback: string) {
  return next.startsWith("/") && !next.startsWith("//") ? next : fallback;
}

// ---------- auth ----------

export async function signup(_: State, f: FormData): Promise<State> {
  const next = safeNext(str(f, "next"), "/onboarding");
  const site = await siteUrl(); // emailed links open on this host (Kickrail or a portal domain)
  const r = await attempt(() => api<{ token: string }>("/auth/signup", { auth: false, body: { name: str(f, "name"), email: str(f, "email"), password: str(f, "password"), next, site } }));
  if (r.error) return { error: r.error };
  await setSession(r.value!.token);
  redirect(`/verify-email?next=${encodeURIComponent(next)}`);
}

export async function resendVerification(_: State, f: FormData): Promise<State> {
  const site = await siteUrl();
  const r = await attempt(() => api<{ already_verified?: boolean }>("/auth/verify/resend", { body: { next: safeNext(str(f, "next"), "/home"), site } }));
  if (r.error) return { error: r.error };
  if (r.value!.already_verified) redirect(safeNext(str(f, "next"), "/home"));
  return { ok: "Sent. Check your inbox." };
}

export async function forgotPassword(_: State, f: FormData): Promise<State> {
  const site = await siteUrl();
  const r = await attempt(() => api("/auth/password/forgot", { auth: false, body: { email: str(f, "email"), site } }));
  return r.error ? { error: r.error } : { ok: "If there's an account for that address, a reset link is on its way. It works for 1 hour." };
}

export async function resetPassword(_: State, f: FormData): Promise<State> {
  const r = await attempt(() => api<{ token: string }>("/auth/password/reset", { auth: false, body: { token: str(f, "token"), password: str(f, "password") } }));
  if (r.error) return { error: r.error };
  await setSession(r.value!.token);
  redirect("/home");
}

export async function login(_: State, f: FormData): Promise<State> {
  const r = await attempt(() => api<{ token: string }>("/auth/login", { auth: false, body: { email: str(f, "email"), password: str(f, "password") } }));
  if (r.error) return { error: r.error };
  await setSession(r.value!.token);
  redirect(safeNext(str(f, "next"), "/home"));
}

export async function logout() {
  await clearSession();
  redirect("/");
}

// ---------- merchant workspace ----------

export async function createWorkspace(_: State, f: FormData): Promise<State> {
  const r = await attempt(() => api<{ merchant: { id: string }; secret_key: string }>("/merchant", { body: { name: str(f, "name"), website: str(f, "website") } }));
  if (r.error) return { error: r.error };
  await setProgram(r.value!.merchant.id);
  return { secret: r.value!.secret_key };
}

export async function switchProgram(id: string) {
  await setProgram(id);
  redirect("/dashboard");
}

export async function updateSettings(_: State, f: FormData): Promise<State> {
  const r = await attempt(() =>
    api("/merchant", {
      method: "PATCH",
      body: {
        name: str(f, "name"),
        website: str(f, "website"),
        cookie_days: num(f, "cookie_days"),
        param_names: str(f, "param_names").split(",").map((s) => s.trim()).filter(Boolean),
        auto_approve: f.get("auto_approve") === "on",
        affiliate_links: f.get("affiliate_links") === "on",
        require_tax_form: f.get("require_tax_form") === "on",
        attribution: f.get("attribution") === "last" ? "last" : "first",
      },
    }),
  );
  revalidatePath("/dashboard", "layout");
  return r.error ? { error: r.error } : { ok: "Saved" };
}

export async function saveEmailSettings(_: State, f: FormData): Promise<State> {
  const emails = Object.fromEntries(f.getAll("kinds").map(String).map((k) => [k, f.get(`email_${k}`) === "on"]));
  const r = await attempt(() => api("/merchant", { method: "PATCH", body: { emails } }));
  revalidatePath("/dashboard", "layout");
  return r.error ? { error: r.error } : { ok: "Saved" };
}

export async function saveBranding(_: State, f: FormData): Promise<State> {
  const body = Object.fromEntries(["logo_url", "color", "headline", "description", "welcome_message", "terms_url", "reply_to"].map((k) => [k, str(f, k) || null]));
  const r = await attempt(() => api("/merchant/branding", { method: "PUT", body: { ...body, headline: body.headline ?? "", description: body.description ?? "", welcome_message: body.welcome_message ?? "" } }));
  revalidatePath("/dashboard", "layout");
  return r.error ? { error: r.error } : { ok: "Saved" };
}

type DomainResult = { domain: { verified: boolean; detail?: string } };

export async function addDomain(_: State, f: FormData): Promise<State> {
  const r = await attempt(() => api<DomainResult>("/merchant/domains", { method: "POST", body: { host: str(f, "host") } }));
  revalidatePath("/dashboard", "layout");
  if (r.error) return { error: r.error };
  const d = r.value!.domain;
  return d.verified ? { ok: "Verified. Your portal is live on this domain." } : { error: `Saved, not verified yet: ${d.detail}` };
}

export async function verifyDomain(host: string): Promise<State> {
  const r = await attempt(() => api<DomainResult>(`/merchant/domains/${encodeURIComponent(host)}/verify`, { method: "POST" }));
  revalidatePath("/dashboard", "layout");
  if (r.error) return { error: r.error };
  const d = r.value!.domain;
  return d.verified ? { ok: "Verified" } : { error: d.detail ?? "Not verified yet" };
}

export async function makePrimaryDomain(host: string) {
  await api(`/merchant/domains/${encodeURIComponent(host)}/primary`, { method: "POST" });
  revalidatePath("/dashboard", "layout");
}

export async function removeDomain(host: string) {
  await api(`/merchant/domains/${encodeURIComponent(host)}`, { method: "DELETE" });
  revalidatePath("/dashboard", "layout");
}

// ---------- billing ----------

export async function startCheckout(plan: string, interval: string): Promise<State> {
  const r = await attempt(() => api<{ url?: string; changed?: boolean }>("/merchant/billing/checkout", { body: { plan, interval } }));
  if (r.error) return { error: r.error };
  if (r.value!.url) redirect(r.value!.url);
  revalidatePath("/dashboard", "layout");
  return { ok: "Plan changed. The difference is prorated on your next invoice." };
}

export async function openBillingPortal(): Promise<State> {
  const r = await attempt(() => api<{ url: string }>("/merchant/billing/portal", { method: "POST" }));
  if (r.error) return { error: r.error };
  redirect(r.value!.url);
}

export async function rotateSecret(): Promise<State> {
  const r = await attempt(() => api<{ secret_key: string }>("/merchant/rotate-secret", { method: "POST" }));
  revalidatePath("/dashboard/settings");
  return r.error ? { error: r.error } : { secret: r.value!.secret_key };
}

export async function connectStripe(_: State, f: FormData): Promise<State> {
  const r = await attempt(() => api("/merchant/stripe", { body: { restricted_key: str(f, "restricted_key") } }));
  revalidatePath("/dashboard", "layout");
  return r.error ? { error: r.error } : { ok: "Stripe connected. Webhook endpoint created." };
}

export async function startStripeOAuth(): Promise<State> {
  const r = await attempt(() => api<{ url: string }>("/merchant/stripe/oauth"));
  if (r.error) return { error: r.error };
  redirect(r.value!.url);
}

export async function disconnectStripe(): Promise<State> {
  const r = await attempt(() => api("/merchant/stripe", { method: "DELETE" }));
  revalidatePath("/dashboard", "layout");
  return r.error ? { error: r.error } : { ok: "Disconnected" };
}

// ---------- campaigns ----------

export async function saveCampaign(_: State, f: FormData): Promise<State> {
  const id = str(f, "id");
  const body = {
    name: str(f, "name"),
    rule_type: str(f, "rule_type"),
    percent: str(f, "rule_type") === "percent" ? num(f, "percent") : undefined,
    flat_cents: str(f, "rule_type") === "flat" ? cents(f, "flat") : undefined,
    currency: str(f, "currency") || "usd",
    duration_mode: str(f, "duration_mode"),
    months: str(f, "duration_mode") === "months" ? num(f, "months") : undefined,
    hold_days: num(f, "hold_days") ?? 0,
    min_payout_cents: cents(f, "min_payout") ?? 0,
    stripe_coupon_id: str(f, "stripe_coupon_id") || null,
    lead_bounty_cents: cents(f, "lead_bounty") ?? 0,
    lead_bounty_currency: str(f, "lead_bounty_currency") || "usd",
    product_rules: productRules(str(f, "product_rules")),
    public: f.get("public") === "on",
    slug: str(f, "slug").toLowerCase() || null,
    landing_url: str(f, "landing_url") || null,
  };
  const r = await attempt(() => api(id ? `/merchant/campaigns/${id}` : "/merchant/campaigns", { method: id ? "PUT" : "POST", body }));
  revalidatePath("/dashboard/campaigns");
  return r.error ? { error: r.error } : { ok: "Saved. Applies to commissions earned from now on." };
}

type ProductRuleRow = { match: "product" | "price"; id: string; label: string; type: "percent" | "flat" | "none"; percent: string; flat: string; currency: string };

function productRules(json: string) {
  const rows: ProductRuleRow[] = json ? JSON.parse(json) : [];
  return rows
    .filter((r) => r.id.trim())
    .map((r) => ({
      match: r.match,
      id: r.id.trim(),
      label: r.label.trim(),
      rule: { type: r.type, percent: r.type === "percent" ? Number(r.percent) : undefined, flat_cents: r.type === "flat" ? Math.round(Number(r.flat) * 100) : undefined, currency: r.currency || "usd" },
    }));
}

export async function makeDefaultCampaign(id: string) {
  await api(`/merchant/campaigns/${id}/default`, { method: "POST" });
  revalidatePath("/dashboard/campaigns");
}

// ---------- affiliates & referrals ----------

export async function updateAffiliate(_: State, f: FormData): Promise<State> {
  const body: Record<string, string> = {};
  for (const k of ["status", "campaign_id", "code"]) if (str(f, k)) body[k] = str(f, k);
  const r = await attempt(() => api<{ warning?: string }>(`/merchant/affiliates/${str(f, "id")}`, { method: "PATCH", body }));
  revalidatePath("/dashboard/affiliates");
  if (r.error) return { error: r.error };
  return r.value!.warning ? { error: r.value!.warning } : { ok: "Saved" };
}

export async function addAffiliate(_: State, f: FormData): Promise<State> {
  const r = await attempt(() =>
    api("/merchant/affiliates", { body: { email: str(f, "email"), name: str(f, "name"), campaign_id: str(f, "campaign_id") || null, send_welcome_email: f.get("send_welcome_email") === "on" } }),
  );
  revalidatePath("/dashboard/affiliates");
  return r.error ? { error: r.error } : { ok: f.get("send_welcome_email") === "on" ? "Added. They got an email with a link to set their password." : "Added, approved, no email sent." };
}

/** Rate override: "campaign" clears it, otherwise a rule that replaces the campaign rate for this affiliate. */
export async function setRateOverride(_: State, f: FormData): Promise<State> {
  const type = str(f, "rate_type");
  const body =
    type === "campaign"
      ? { clear_rate_override: true }
      : { rate_override: { type, percent: type === "percent" ? num(f, "percent") : undefined, flat_cents: type === "flat" ? cents(f, "flat") : undefined, currency: str(f, "currency") || "usd" } };
  const r = await attempt(() => api(`/merchant/affiliates/${str(f, "id")}`, { method: "PATCH", body }));
  revalidatePath(`/dashboard/affiliates`, "layout");
  return r.error ? { error: r.error } : { ok: "Saved. Applies to commissions earned from now on." };
}

export async function addMerchantLink(_: State, f: FormData): Promise<State> {
  const id = str(f, "id");
  const r = await attempt(() => api(`/merchant/affiliates/${id}/links`, { body: { token: str(f, "token").toLowerCase(), landing_url: str(f, "landing_url") || null, label: str(f, "label") } }));
  revalidatePath(`/dashboard/affiliates`, "layout");
  return r.error ? { error: r.error } : { ok: "Link added" };
}

export async function deleteMerchantLink(affiliateId: string, linkId: string) {
  await api(`/merchant/affiliates/${affiliateId}/links/${linkId}`, { method: "DELETE" });
  revalidatePath(`/dashboard/affiliates`, "layout");
}

export async function addCode(_: State, f: FormData): Promise<State> {
  const r = await attempt(() => api<{ warning?: string }>(`/merchant/affiliates/${str(f, "id")}/codes`, { body: { code: str(f, "code").toUpperCase() } }));
  revalidatePath(`/dashboard/affiliates`, "layout");
  if (r.error) return { error: r.error };
  return r.value!.warning ? { error: `Added, but: ${r.value!.warning}` } : { ok: "Code added" };
}

export async function deleteCode(affiliateId: string, codeId: string) {
  await api(`/merchant/affiliates/${affiliateId}/codes/${codeId}`, { method: "DELETE" });
  revalidatePath(`/dashboard/affiliates`, "layout");
}

export async function setAffiliateStatus(id: string, status: string) {
  await api(`/merchant/affiliates/${id}`, { method: "PATCH", body: { status } });
  revalidatePath("/dashboard/affiliates");
}

export async function reviewReferral(id: string, verdict: "clear" | "reject") {
  await api(`/merchant/referrals/${id}/${verdict}`, { method: "POST" });
  revalidatePath("/dashboard", "layout");
}

export async function deleteRecord(kind: "referrals" | "commissions", id: string, reason: string): Promise<State> {
  const r = await attempt(() => api(`/merchant/${kind}/${id}`, { method: "DELETE", body: { reason: reason.trim() || null } }));
  revalidatePath("/dashboard", "layout");
  return r.error ? { error: r.error } : { ok: "Deleted" };
}

// ---------- team ----------

export async function inviteMember(_: State, f: FormData): Promise<State> {
  const r = await attempt(() => api("/merchant/team/invites", { body: { email: str(f, "email") } }));
  revalidatePath("/dashboard/team");
  return r.error ? { error: r.error } : { ok: `Invite sent to ${str(f, "email")}` };
}

export async function revokeInvite(id: string) {
  await api(`/merchant/team/invites/${id}`, { method: "DELETE" });
  revalidatePath("/dashboard/team");
}

export async function removeMember(userId: string) {
  await api(`/merchant/team/members/${userId}`, { method: "DELETE" });
  revalidatePath("/dashboard", "layout");
}

export async function acceptInvite(token: string) {
  let ok = false;
  try {
    const r = await api<{ merchant: { id: string } }>(`/auth/invites/${token}/accept`, { method: "POST" });
    await setProgram(r.merchant.id);
    ok = true;
  } catch (e) {
    if (e instanceof ApiError && e.status === 401) redirect(`/login?next=/invite/${token}`);
    if (!(e instanceof ApiError)) throw e;
    redirect(`/invite/${token}?error=${encodeURIComponent(e.message)}`);
  }
  if (ok) redirect("/dashboard");
}

// ---------- developers ----------

const events = (f: FormData) => {
  const picked = f.getAll("events").map(String);
  return picked.length ? picked : ["*"];
};

export async function createWebhook(_: State, f: FormData): Promise<State> {
  const r = await attempt(() => api<{ secret: string }>("/merchant/webhooks", { body: { url: str(f, "url"), description: str(f, "description"), events: f.get("all_events") === "on" ? ["*"] : events(f) } }));
  revalidatePath("/dashboard/developers");
  return r.error ? { error: r.error } : { secret: r.value!.secret };
}

export async function updateWebhook(_: State, f: FormData): Promise<State> {
  const r = await attempt(() =>
    api(`/merchant/webhooks/${str(f, "id")}`, { method: "PUT", body: { url: str(f, "url"), description: str(f, "description"), events: f.get("all_events") === "on" ? ["*"] : events(f), enabled: f.get("enabled") === "on" } }),
  );
  revalidatePath("/dashboard/developers");
  return r.error ? { error: r.error } : { ok: "Saved" };
}

export async function deleteWebhook(id: string) {
  await api(`/merchant/webhooks/${id}`, { method: "DELETE" });
  revalidatePath("/dashboard/developers");
}

export async function revealWebhookSecret(_: State, f: FormData): Promise<State> {
  const r = await attempt(() => api<{ secret: string }>(`/merchant/webhooks/${str(f, "id")}/secret`));
  return r.error ? { error: r.error } : { secret: r.value!.secret };
}

export async function testWebhook(_: State, f: FormData): Promise<State> {
  const r = await attempt(() => api<{ ok: boolean; response_status?: number; last_error?: string }>(`/merchant/webhooks/${str(f, "id")}/test`, { method: "POST" }));
  revalidatePath("/dashboard/developers");
  if (r.error) return { error: r.error };
  return r.value!.ok ? { ok: `Delivered: your endpoint answered ${r.value!.response_status}` } : { error: `Not delivered: ${r.value!.last_error ?? `HTTP ${r.value!.response_status}`}` };
}

export async function retryDelivery(id: string) {
  await api(`/merchant/webhooks/deliveries/${id}/retry`, { method: "POST" });
  revalidatePath("/dashboard/developers");
}

// ---------- payouts ----------

export async function createPayout(_: State, f: FormData): Promise<State> {
  const method = str(f, "method");
  const body: Record<string, unknown> = { currency: str(f, "currency"), method };
  if (method === "manual" || method === "paypal") {
    body.affiliate_ids = f.getAll("affiliate_ids").map(String);
    body.reference = str(f, "reference");
    if (!(body.affiliate_ids as string[]).length) return { error: method === "manual" ? "Tick the affiliates you've paid." : "Tick who to pay." };
  }
  const r = await attempt(() => api<{ funding_url?: string; items: unknown[] }>("/merchant/payouts", { body }));
  revalidatePath("/dashboard/payouts");
  if (r.error) return { error: r.error };
  if (r.value!.funding_url) redirect(r.value!.funding_url);
  const n = r.value!.items.length;
  const who = `${n} affiliate${n === 1 ? "" : "s"}`;
  return { ok: method === "paypal" ? `Sent a PayPal batch to ${who}. It shows as paid once PayPal confirms each item.` : `Marked ${who} as paid.` };
}

export async function syncPayout(id: string) {
  await api(`/merchant/payouts/${id}/sync`, { method: "POST" }).catch(() => undefined);
  revalidatePath("/dashboard/payouts");
}

export async function connectPayPal(_: State, f: FormData): Promise<State> {
  const r = await attempt(() => api("/merchant/paypal", { method: "PUT", body: { client_id: str(f, "client_id"), secret: str(f, "secret"), mode: str(f, "mode") || "sandbox" } }));
  revalidatePath("/dashboard", "layout");
  return r.error ? { error: r.error } : { ok: "PayPal connected" };
}

export async function disconnectPayPal() {
  await api("/merchant/paypal", { method: "DELETE" });
  revalidatePath("/dashboard", "layout");
}

export async function undoPayout(id: string) {
  await api(`/merchant/payouts/${id}/undo`, { method: "POST" });
  revalidatePath("/dashboard/payouts");
}

export async function cancelPayout(id: string) {
  await api(`/merchant/payouts/${id}/cancel`, { method: "POST" });
  revalidatePath("/dashboard/payouts");
}

// ---------- affiliate side ----------

export async function joinProgram(slug: string, campaign: string | null = null) {
  let id: string;
  try {
    id = (await api<{ id: string }>(`/programs/${slug}/join`, { method: "POST", body: { campaign } })).id;
  } catch (e) {
    if (e instanceof ApiError && e.status === 401) redirect(`/signup?next=/join/${slug}${campaign ? `/${campaign}` : ""}`);
    throw e;
  }
  redirect(`/a/${id}`);
}

export async function changeToken(_: State, f: FormData): Promise<State> {
  const r = await attempt(() => api(`/portal/${str(f, "id")}/token`, { method: "PUT", body: { token: str(f, "token").toLowerCase() } }));
  revalidatePath(`/a/${str(f, "id")}`);
  return r.error ? { error: r.error } : { ok: "Link updated" };
}

export async function addOwnLink(_: State, f: FormData): Promise<State> {
  const id = str(f, "id");
  const r = await attempt(() => api(`/portal/${id}/links`, { body: { token: str(f, "token").toLowerCase(), landing_url: str(f, "landing_url") || null, label: str(f, "label") } }));
  revalidatePath(`/a/${id}`);
  return r.error ? { error: r.error } : { ok: "Link added" };
}

export async function deleteOwnLink(affiliateId: string, linkId: string) {
  await api(`/portal/${affiliateId}/links/${linkId}`, { method: "DELETE" });
  revalidatePath(`/a/${affiliateId}`);
}

export async function saveTaxInfo(_: State, f: FormData): Promise<State> {
  const form = str(f, "form");
  const body = {
    form,
    legal_name: str(f, "legal_name"),
    business_name: str(f, "business_name"),
    classification: str(f, "classification") || "individual",
    country: (form === "w9" ? "US" : str(f, "country")).toUpperCase(),
    address: str(f, "address"),
    tin: str(f, "tin"),
    date_of_birth: str(f, "date_of_birth") || null,
    treaty_country: str(f, "treaty_country").toUpperCase() || null,
    signature: str(f, "signature"),
    certify: f.get("certify") === "on",
  };
  const r = await attempt(() => api("/tax-info", { method: "PUT", body }));
  revalidatePath("/a", "layout");
  return r.error ? { error: r.error } : { ok: "Tax form signed and saved." };
}

export async function claimAccount(_: State, f: FormData): Promise<State> {
  const r = await attempt(() => api<{ token: string }>("/auth/claim", { auth: false, body: { token: str(f, "token"), password: str(f, "password"), name: str(f, "name") || null } }));
  if (r.error) return { error: r.error };
  await setSession(r.value!.token);
  redirect("/a");
}

export async function savePayoutDetails(_: State, f: FormData): Promise<State> {
  const r = await attempt(() => api("/payout-account/details", { method: "PUT", body: { method: str(f, "method"), value: str(f, "value") } }));
  if (r.error) return { error: r.error };
  revalidatePath("/a/payouts");
  return { ok: "Saved. Programs that pay manually will send your money here." };
}

export async function startPayoutOnboarding(_: State, f: FormData): Promise<State> {
  const r = await attempt(() => api<{ url: string }>("/payout-account/onboard", { body: { country: str(f, "country") || "US" } }));
  if (r.error) return { error: r.error };
  redirect(r.value!.url);
}

export async function openExpressDashboard(): Promise<State> {
  const r = await attempt(() => api<{ url: string }>("/payout-account/dashboard", { method: "POST" }));
  if (r.error) return { error: r.error };
  redirect(r.value!.url);
}

export async function startRewardfulImport(_: State, f: FormData): Promise<State> {
  // The secret goes straight to the backend for this one run; it isn't kept anywhere.
  const r = await attempt(() => api("/merchant/import/rewardful", { method: "POST", body: { api_secret: str(f, "api_secret"), send_claim_emails: f.get("send_claim_emails") === "on" } }));
  revalidatePath("/dashboard/settings");
  return r.error ? { error: r.error } : { ok: "Import started" };
}
