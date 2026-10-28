import { redirect } from "next/navigation";
import { maybe } from "@/lib/backend";
import type { Me, PartnerMe } from "@/lib/me";

/** Where signing in lands: the merchant dashboard, the affiliate portal, or onboarding.
 * The dashboard and the portal are separate logins; either (or both) can be signed in. */
export default async function Home() {
  const [op, pt] = await Promise.all([maybe<Me>("/auth/me"), maybe<PartnerMe>("/partner/auth/me")]);
  const to = (path: string, user: Me["user"]) => redirect(user.email_verified ? path : `/verify-email?next=${encodeURIComponent(path)}`);
  if (op?.merchant) to("/dashboard", op.user);
  if (pt && (pt.affiliations || !op)) to("/a", pt.user);
  if (op) to("/onboarding", op.user);
  redirect("/login?next=/home");
}
