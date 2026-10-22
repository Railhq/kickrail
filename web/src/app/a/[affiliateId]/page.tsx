import { notFound } from "next/navigation";
import Link from "next/link";
import { cache } from "react";
import { PortalView } from "@/components/PortalView";
import { authed } from "@/lib/backend";
import type { PortalView as View } from "@/lib/types";

// Shared by the metadata and the page, so the portal is fetched once per request.
const load = cache((affiliateId: string) => authed<View>(`/portal/${affiliateId}`, `/a/${affiliateId}`));

export async function generateMetadata({ params }: { params: Promise<{ affiliateId: string }> }) {
  const d = await load((await params).affiliateId);
  if (!d) return {};
  return { title: d.program.name, icons: d.program.branding?.favicon_url ? { icon: d.program.branding.favicon_url } : undefined };
}

export default async function ProgramDetail({ params }: { params: Promise<{ affiliateId: string }> }) {
  const { affiliateId } = await params;
  const d = await load(affiliateId);
  if (!d) notFound();
  return <PortalView d={d} back={<Link href="/a" className="eyebrow hover:text-fg">← Programs</Link>} />;
}
