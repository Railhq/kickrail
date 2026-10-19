import Link from "next/link";
import { Logo } from "@/components/Logo";

export default function LegalLayout({ children }: { children: React.ReactNode }) {
  return (
    <div className="min-h-screen">
      <header className="border-b border-line bg-surface/70">
        <div className="mx-auto flex max-w-6xl items-center justify-between px-4 py-4 sm:px-6">
          <Logo />
          <nav className="flex items-center gap-2 text-sm">
            <Link href="/docs" className="btn hidden hover:bg-sunk sm:inline-flex">Docs</Link>
            <Link href="/login" className="btn hover:bg-sunk">Sign in</Link>
            <Link href="/signup" className="btn btn-primary">Start a program</Link>
          </nav>
        </div>
      </header>
      <main className="mx-auto max-w-3xl px-4 py-12 sm:px-6">{children}</main>
      <footer className="border-t border-line">
        <div className="mx-auto flex max-w-3xl flex-wrap gap-x-8 gap-y-2 px-4 py-8 text-sm text-muted sm:px-6">
          <Link href="/terms" className="hover:text-fg">Terms</Link>
          <Link href="/privacy" className="hover:text-fg">Privacy</Link>
          <Link href="/docs" className="hover:text-fg">Docs</Link>
        </div>
      </footer>
    </div>
  );
}
