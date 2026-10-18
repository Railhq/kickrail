import "server-only";
import { redirect } from "next/navigation";
import { authed } from "./backend";

export type Me = {
  user: { id: string; email: string; name: string; payouts_enabled: boolean; can_be_paid: boolean; email_verified: boolean };
  /** The program the dashboard is on; `merchants` is every program the user runs. */
  merchant: { id: string; name: string; slug: string } | null;
  merchants: { id: string; name: string; slug: string }[];
  affiliations: number;
};

/** The signed-in user. Sends signed-out users to /login and unverified ones to /verify-email. */
export async function getMe(next: string): Promise<Me> {
  const me = (await authed<Me>("/auth/me", next)) as Me;
  if (!me.user.email_verified) redirect(`/verify-email?next=${encodeURIComponent(next)}`);
  return me;
}
