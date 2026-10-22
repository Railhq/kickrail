import Link from "next/link";
import { notFound } from "next/navigation";
import { cache } from "react";
import { ApiError, api } from "@/lib/backend";
import { date } from "@/lib/format";
import type { Terms } from "@/lib/types";
import type { Program } from "../../JoinView";

type Page = { program: Program; terms: Terms };

const load = cache(async (slug: string) => {
  try {
    return await api<Page>(`/programs/${encodeURIComponent(slug)}/terms`, { auth: false });
  } catch (e) {
    if (e instanceof ApiError && e.status === 404) notFound();
    throw e;
  }
});

export async function generateMetadata({ params }: { params: Promise<{ slug: string }> }) {
  const { program: p, terms } = await load((await params).slug);
  return { title: `${terms.title} · ${p.name}`, icons: p.branding.favicon_url ? { icon: p.branding.favicon_url } : undefined };
}

export default async function TermsPage({ params }: { params: Promise<{ slug: string }> }) {
  const { slug } = await params;
  const { program: p, terms } = await load(slug);
  const b = p.branding;
  return (
    <div className="mx-auto min-h-screen max-w-2xl px-4 py-12">
      <Link href={`/join/${slug}`} className="inline-block">
        {b.logo_url ? (
          // eslint-disable-next-line @next/next/no-img-element
          <img src={b.logo_url} alt={p.name} className="h-10 w-auto object-contain" />
        ) : (
          <span className="font-display text-xl tracking-tight">{p.name}</span>
        )}
      </Link>
      <article className="card mt-10 p-7 sm:p-10" style={b.color ? { borderTop: `4px solid ${b.color}` } : undefined}>
        <p className="eyebrow">{p.name} affiliate program</p>
        <h1 className="mt-2 font-display text-4xl tracking-tight">{terms.title}</h1>
        <p className="mt-2 text-sm text-muted">Last updated {date(terms.updated_at)}</p>
        {/* Cleaned to a short allowlist of tags on the server when it was saved. */}
        <div className="prose-terms mt-8 text-[15px] leading-relaxed" dangerouslySetInnerHTML={{ __html: terms.html }} />
      </article>
      <p className="mt-6 text-center text-sm"><Link className="link" href={`/join/${slug}`}>Join the program</Link></p>
    </div>
  );
}
