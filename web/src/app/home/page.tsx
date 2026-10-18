import { redirect } from "next/navigation";
import { getMe } from "@/lib/me";

/** Where signing in lands: the merchant dashboard, the affiliate portal, or onboarding. */
export default async function Home() {
  const me = await getMe("/home");
  redirect(me.merchant ? "/dashboard" : me.affiliations ? "/a" : "/onboarding");
}
