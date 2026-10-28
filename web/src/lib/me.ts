import "server-only";
import { redirect } from "next/navigation";
import { authed, maybe } from "./backend";

export type Me = {
  user: { id: string; email: string; name: string; payouts_enabled: boolean; can_be_paid: boolean; email_verified: boolean };
  /** The program the dashboard is on; `merchants` is every program the user runs. */
  merchant: { id: string; name: string; slug: string } | null;
  merchants: { id: string; name: string; slug: string }[];
};

/** The signed-in affiliate (their own login, separate from the dashboard's). */
export type PartnerMe = { user: Me["user"]; affiliations: number };

/** The signed-in user. Sends signed-out users to /login and unverified ones to /verify-email. */
export async function getMe(next: string): Promise<Me> {
  const me = (await authed<Me>("/auth/me", next)) as Me;
  if (!me.user.email_verified) redirect(`/verify-email?next=${encodeURIComponent(next)}`);
  return me;
}

/** The signed-in affiliate. Sends signed-out ones to /login and unverified ones to /verify-email. */
export async function getPartnerMe(next: string): Promise<PartnerMe> {
  const me = (await authed<PartnerMe>("/partner/auth/me", next)) as PartnerMe;
  if (!me.user.email_verified) redirect(`/verify-email?next=${encodeURIComponent(next)}`);
  return me;
}

/** How many programs the affiliate login in this browser promotes (0 when there is none). */
export async function affiliations(): Promise<number> {
  return (await maybe<PartnerMe>("/partner/auth/me"))?.affiliations ?? 0;
}
