import Link from "next/link";
import { Logo } from "@/components/Logo";
import { api, portalSlug } from "@/lib/backend";

type Brand = { name: string; branding: { logo_url: string | null } };

/** On a program's portal domain, the sign-in pages carry that program's name and logo. */
async function portalBrand(): Promise<Brand | null> {
  const slug = await portalSlug();
  if (!slug) return null;
  try {
    return await api<Brand>(`/programs/${encodeURIComponent(slug)}`, { auth: false });
  } catch {
    return null;
  }
}

export default async function AuthLayout({ children }: { children: React.ReactNode }) {
  const brand = await portalBrand();
  return (
    <div className="grid min-h-screen lg:grid-cols-[1fr_1.1fr]">
      <div className="flex flex-col px-4 py-6 sm:px-10">
        {brand ? (
          <Link href="/" className="flex items-center gap-2 text-[17px] font-semibold tracking-tight">
            {/* eslint-disable-next-line @next/next/no-img-element */}
            {brand.branding.logo_url ? <img src={brand.branding.logo_url} alt={brand.name} className="h-8 w-auto object-contain" /> : brand.name}
          </Link>
        ) : (
          <Logo />
        )}
        <div className="mx-auto my-auto w-full max-w-sm py-12">{children}</div>
      </div>
      <aside className="relative hidden overflow-hidden bg-ink p-12 text-white lg:flex lg:flex-col lg:justify-end">
        <div className="absolute -right-24 -top-24 h-96 w-96 rounded-full bg-signal/20 blur-3xl" />
        <div className="absolute inset-0 bg-[linear-gradient(to_right,rgba(255,255,255,0.04)_1px,transparent_1px)] bg-[size:56px_100%]" />
        <p className="relative font-display text-5xl leading-[1.05] tracking-tight">
          One login for your program
          <br />
          <span className="italic text-signal">and every program you promote.</span>
        </p>
        <p className="relative mt-6 max-w-md text-sm leading-relaxed text-ink-muted">Clicks, signups, commissions and payouts, recorded the moment Stripe sees them.</p>
      </aside>
    </div>
  );
}
