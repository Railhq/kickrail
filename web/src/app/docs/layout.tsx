import type { Metadata } from "next";
import Link from "next/link";
import { Logo } from "@/components/Logo";
import { DocsNav, DocsPager } from "./DocsNav";

export const metadata: Metadata = {
  title: { default: "Docs", template: "%s · Kickrail docs" },
  description: "How to install Kickrail, report referrals from your server, pay affiliates, and use the API and webhooks.",
};

export default function DocsLayout({ children }: { children: React.ReactNode }) {
  return (
    <div className="min-h-screen">
      <header className="border-b border-line bg-surface/70">
        <div className="mx-auto flex max-w-6xl items-center justify-between px-4 py-4 sm:px-6">
          <div className="flex items-center gap-3">
            <Logo />
            <span className="font-mono text-xs text-muted">/ docs</span>
          </div>
          <nav className="flex items-center gap-2 text-sm">
            <Link href="/#pricing" className="btn hidden hover:bg-sunk sm:inline-flex">Pricing</Link>
            <Link href="/login" className="btn hover:bg-sunk">Sign in</Link>
            <Link href="/signup" className="btn btn-primary">Start a program</Link>
          </nav>
        </div>
      </header>
      <div className="mx-auto grid max-w-6xl gap-10 px-4 py-10 sm:px-6 lg:grid-cols-[220px_minmax(0,1fr)]">
        <aside className="lg:sticky lg:top-6 lg:self-start">
          <details className="lg:hidden" >
            <summary className="btn btn-secondary w-full cursor-pointer">Contents</summary>
            <div className="mt-4"><DocsNav /></div>
          </details>
          <div className="hidden lg:block"><DocsNav /></div>
        </aside>
        <main className="min-w-0 max-w-3xl">
          {children}
          <DocsPager />
        </main>
      </div>
    </div>
  );
}
