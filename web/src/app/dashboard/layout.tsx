import Link from "next/link";
import { redirect } from "next/navigation";
import { logout } from "@/app/actions";
import { Logo } from "@/components/Logo";
import { api } from "@/lib/backend";
import { getMe } from "@/lib/me";
import type { PlanSummary } from "@/lib/types";
import { Nav } from "./Nav";
import { ProgramSwitcher } from "./ProgramSwitcher";

export default async function DashboardLayout({ children }: { children: React.ReactNode }) {
  const me = await getMe("/dashboard");
  if (!me.merchant) redirect("/onboarding");
  const { flagged, plan } = await api<{ flagged: number; plan: PlanSummary }>("/merchant/overview");
  return (
    <div className="flex min-h-screen flex-col md:flex-row">
      <aside className="bg-ink p-3 text-white md:sticky md:top-0 md:flex md:h-screen md:w-60 md:shrink-0 md:flex-col md:p-4">
        <div className="flex items-center justify-between px-2 md:block">
          <Logo href="/dashboard" dark />
          <div className="mt-5 hidden md:block">
            <ProgramSwitcher me={me} />
          </div>
        </div>
        <div className="mt-3 md:hidden">
          <ProgramSwitcher me={me} />
        </div>
        <div className="mt-3 md:mt-5">
          <Nav flagged={flagged} />
        </div>
        <div className="mt-auto hidden space-y-0.5 border-t border-ink-line pt-3 text-sm text-ink-muted md:block">
          {me.affiliations > 0 && <Link href="/a" className="block rounded-lg px-3 py-1.5 hover:text-white">Programs I promote</Link>}
          <form action={logout}><button className="w-full rounded-lg px-3 py-1.5 text-left hover:text-white">Sign out</button></form>
        </div>
      </aside>
      <main className="min-w-0 flex-1">
        <div className="mx-auto max-w-5xl p-4 sm:p-6 md:px-10 md:py-10">
          <PlanBanner plan={plan} />
          {children}
        </div>
      </main>
    </div>
  );
}

function PlanBanner({ plan }: { plan: PlanSummary }) {
  let text: string | null = null;
  if (plan.comped) return null;
  if (plan.status === "past_due") text = "Your last Kickrail payment failed. Update your card to keep your plan.";
  else if (plan.over_limit) text = "Your affiliates brought in more than your plan covers two months running. Tracking keeps going; see which plan fits.";
  else if (plan.status === "trial_ended") text = "Your free trial ended and this program is on Free. Tracking keeps running; pick a plan to get the paid features back.";
  else if (plan.status === "trialing" && !plan.subscribed && plan.trial_ends_at) {
    const days = Math.ceil((new Date(plan.trial_ends_at).getTime() - Date.now()) / 86_400_000);
    if (days <= 3) text = `Your ${plan.name} trial ends in ${days} ${days === 1 ? "day" : "days"}. Pick a plan to keep its features.`;
  }
  if (!text) return null;
  return (
    <div className="mb-6 flex flex-wrap items-center justify-between gap-3 rounded-xl border border-amber-300 bg-amber-50 px-4 py-3 text-sm text-amber-900">
      <span>{text}</span>
      <Link href="/dashboard/billing" className="btn btn-secondary">Billing</Link>
    </div>
  );
}
