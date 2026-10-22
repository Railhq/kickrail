import type { Fx } from "./format";

export type Merchant = {
  id: string;
  name: string;
  slug: string;
  website: string;
  public_key: string;
  secret_key_hint: string;
  owner_id: string;
  settings: { cookie_days: number; param_names: string[]; auto_approve: boolean; affiliate_links: boolean; require_tax_form: boolean; attribution: "first" | "last"; display_currency: string; emails: Record<string, boolean> };
  branding: Branding;
  portal_domains: PortalDomain[];
  domain_limit: number;
  plan: PlanSummary;
  portal_url: string;
  join_url: string;
  cname_target: string;
  stripe: { account_id: string; account_name: string; livemode: boolean; connected_at: string; mode: "oauth" | "key" } | null;
  stripe_oauth: boolean;
  paypal: { client_id_hint: string; mode: "sandbox" | "live"; connected_at: string } | null;
  snippet: string;
};

export type PortalDomain = { host: string; verified: boolean; primary?: boolean; over_limit: boolean; detail?: string; https?: boolean; https_detail?: string; checked_at?: string; verified_at?: string };

export type PlanId = "free" | "starter" | "growth" | "scale";

export type PlanSummary = {
  id: PlanId;
  name: string;
  status: "active" | "trialing" | "trial_ended" | "past_due" | "comped" | string;
  comped: boolean;
  trial_ends_at: string | null;
  interval: "month" | "year" | null;
  current_period_end: string | null;
  cancel_at_period_end: boolean;
  subscribed: boolean;
  revenue_cap: number | null;
  branding: boolean;
  over_limit: boolean;
  suggested_plan: PlanId | null;
  limits: { domains: number; campaigns: number; teammates: number; creator_codes: boolean; api: boolean; stripe_payouts: boolean };
};

export type Plan = {
  id: PlanId;
  name: string;
  month: number;
  year: number;
  revenue_cap: number;
  domains: number;
  campaigns: number;
  teammates: number;
  creator_codes: boolean;
  api: boolean;
  stripe_payouts: boolean;
  branding: boolean;
  priority_support: boolean;
};

export type BillingInfo = {
  plan: PlanSummary;
  plans: Plan[];
  usage: { this_month_cents: number; months: { month: string; revenue_cents: number }[]; cap_cents: number | null; over_limit: boolean; suggested_plan: PlanId | null };
  teammates: number;
  campaigns: number;
  domains: number;
  enabled: boolean;
  can_manage: boolean;
};

export type Branding = { logo_url?: string | null; color?: string | null; headline?: string | null; description?: string | null; welcome_message?: string | null; terms_url?: string | null; reply_to?: string | null };

export type Rule = { type: "percent"; bps: number } | { type: "flat"; cents: number; currency: string } | { type: "none" };

export type ProductRule = { match: "product" | "price"; id: string; label: string; rule: Rule; description: string };

export type RewardTrigger = "signup" | "first_payment" | "every_payment";

export type CustomReward = {
  type: "custom";
  affiliate: { description: string; on: RewardTrigger; limit: "once" | "per_referral" };
  customer: { description: string; on: "signup" | "first_payment" } | null;
};

export type Reward = {
  id: string;
  recipient: "affiliate" | "customer";
  description: string;
  trigger: RewardTrigger;
  status: "earned" | "fulfilled" | "void";
  held?: boolean;
  affiliate_id: string;
  referral_id: string;
  campaign_id: string;
  note?: string | null;
  void_reason?: string;
  fulfilled_at?: string | null;
  created_at: string;
  affiliate_name?: string;
  customer_email?: string | null;
};

export type Campaign = {
  id: string;
  name: string;
  rule: { type: "percent"; bps: number } | { type: "flat"; cents: number; currency: string };
  duration: { mode: "once" | "forever" } | { mode: "months"; months: number };
  hold_days: number;
  min_payout_cents: number;
  stripe_coupon_id: string | null;
  is_default: boolean;
  description: string;
  lead_bounty: { cents: number; currency: string } | null;
  reward: CustomReward | null;
  product_rules: ProductRule[];
  public: boolean;
  slug: string | null;
  landing_url: string | null;
  join_url: string | null;
};

export type AffiliateLink = { id: string; token: string; url: string; landing_url: string | null; label: string; created_at: string };
export type AffiliateCode = { id: string; code: string; redeemable_at_checkout: boolean; created_at: string };

export type Affiliate = {
  id: string;
  name: string;
  email: string;
  campaign_name: string;
  status: "pending" | "approved" | "rejected";
  token: string;
  code?: string;
  stripe_promotion_code?: string;
  campaign_id: string;
  link: string;
  payouts_enabled: boolean;
  can_be_paid: boolean;
  clicks: number;
  leads: number;
  customers: number;
  earned: Record<string, number>;
  paid: Record<string, number>;
  links: AffiliateLink[];
  codes: AffiliateCode[];
  tax_form: "w9" | "w8ben" | "w8bene" | null;
  rate_override?: Rule | null;
  rate_override_description: string | null;
  metadata?: Record<string, string>;
  created_at: string;
};

export type Referral = {
  id: string;
  affiliate_id: string;
  affiliate_name: string;
  email?: string;
  external_user_id?: string;
  stripe_customer_id?: string;
  source: string;
  status: "lead" | "customer";
  flags: { kind: string; detail: string }[];
  flags_cleared?: boolean;
  rejected?: boolean;
  test?: boolean;
  first_paid_at?: string | null;
  rewardful_id?: string;
  created_at: string;
};

/** One page of a dashboard list. */
export type Page<T> = { items: T[]; total: number; page: number; page_size: number };

export type ReferralDetail = Referral & {
  rewards: Reward[];
  affiliate: { id: string; name: string; email: string; token: string };
  campaign: { id: string; name: string } | null;
  click: { token: string; landing_url: string; referrer: string; created_at: string } | null;
  // The link token or creator code that brought them in; url for links imported from Rewardful.
  via?: { token?: string; code?: string; url?: string };
  commissions: Commission[];
};

export type Commission = {
  id: string;
  affiliate_id: string;
  affiliate_name: string;
  amount_cents: number;
  base_cents: number;
  currency: string;
  status: "pending" | "paid" | "void";
  held?: boolean;
  due_at: string;
  source_key: string;
  void_reason?: string;
  payout_id?: string;
  referral_id?: string;
  customer?: string | null;
  created_at: string;
};

export type PayoutDetails = { method: "paypal" | "wise" | "bank" | "other"; value: string };

export type UpcomingLine = {
  affiliate_id: string;
  name: string;
  email: string;
  amounts: Record<string, number>;
  count: number;
  held: number;
  under_minimum: boolean;
  next_due_at: string | null;
};

export type PayableLine = {
  affiliate_id: string;
  name: string;
  email: string;
  currency: string;
  amount_cents: number;
  commission_ids: string[];
  payouts_enabled: boolean;
  payout_details: PayoutDetails | null;
  paypal_email: string | null;
  tax_form: string | null;
  needs_tax_form: boolean;
};

export type Payout = {
  id: string;
  currency: string;
  method: "stripe" | "manual" | "paypal";
  status: string;
  total_cents: number;
  fee_cents: number;
  items: { affiliate_id: string; amount_cents: number; transfer_id?: string; error?: string; status?: string }[];
  funding_url?: string;
  reference?: string;
  created_at: string;
  paid_at?: string;
};

/** What an affiliate sees for one program: GET /portal/{id}, and GET /merchant/affiliates/{id}/view for "view as". */
export type PortalView = {
  affiliate_id: string;
  status: string;
  program: { slug: string; name: string; website: string; terms: string | null; hold_days: number | null; branding: Branding; powered_by: boolean };
  min_payout_cents: number;
  link: string;
  test_link: string;
  token: string;
  code?: string;
  code_redeemable_at_checkout: boolean;
  links: AffiliateLink[];
  codes: AffiliateCode[];
  can_add_links: boolean;
  last_test: { at: string; url: string } | null;
  fx: Fx;
  payouts_enabled: boolean;
  can_be_paid: boolean;
  has_tax_form: boolean;
  tax_form_required: boolean;
  clicks: number;
  clicks_30d: number;
  leads: number;
  customers: number;
  totals: Record<string, { in_hold: number; payable: number; paid: number }>;
  commissions: { id: string; kind: "lead" | "sale"; amount_cents: number; currency: string; status: string; held_for_review: boolean; clawback: boolean; due_at: string; paid_at?: string; created_at: string; void_reason?: string }[];
  reward_mode: "cash" | "custom";
  rewards: { id: string; description: string; status: "earned" | "fulfilled"; held_for_review: boolean; created_at: string; fulfilled_at?: string | null }[];
};

export type Import = {
  id: string;
  source: "rewardful";
  status: "running" | "done" | "failed" | "stopped";
  step: string | null;
  counts: Record<string, number>;
  totals: Record<string, number>;
  warnings: string[];
  error: string | null;
  send_claim_emails: boolean;
  only: string[];
  started_at: string;
  finished_at: string | null;
};
