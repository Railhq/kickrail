import Link from "next/link";
import { logout } from "@/app/actions";
import { Logo } from "@/components/Logo";
import { getMe } from "@/lib/me";

export default async function PortalLayout({ children }: { children: React.ReactNode }) {
  const me = await getMe("/a");
  return (
    <div className="min-h-screen">
      <header className="sticky top-0 z-10 border-b border-line bg-bg/85 backdrop-blur">
        <div className="mx-auto flex max-w-4xl flex-wrap items-center justify-between gap-3 px-4 py-3.5 sm:px-6">
          <div className="flex items-center gap-3">
            <Logo href="/a" />
            <span className="rounded-md border border-line px-1.5 py-0.5 font-mono text-[10px] uppercase tracking-[0.12em] text-muted">Affiliate</span>
          </div>
          <nav className="flex items-center gap-1 text-sm text-muted">
            <Link href="/a" className="rounded-lg px-2.5 py-1.5 hover:bg-sunk hover:text-fg">Programs</Link>
            <Link href="/a/payouts" className="rounded-lg px-2.5 py-1.5 hover:bg-sunk hover:text-fg">
              Payouts{!me.user.can_be_paid && <span className="ml-1 inline-block h-1.5 w-1.5 rounded-full bg-amber-500 align-middle" />}
            </Link>
            {me.merchant && <Link href="/dashboard" className="rounded-lg px-2.5 py-1.5 hover:bg-sunk hover:text-fg">My program</Link>}
            <form action={logout}><button className="rounded-lg px-2.5 py-1.5 hover:bg-sunk hover:text-fg">Sign out</button></form>
          </nav>
        </div>
      </header>
      <main className="mx-auto max-w-4xl px-4 pb-16 pt-10 sm:px-6">{children}</main>
    </div>
  );
}
