import { notFound } from "next/navigation";
import Link from "next/link";
import { PortalView } from "@/components/PortalView";
import { authed } from "@/lib/backend";
import type { PortalView as View } from "@/lib/types";

export default async function ProgramDetail({ params }: { params: Promise<{ affiliateId: string }> }) {
  const { affiliateId } = await params;
  const d = await authed<View>(`/portal/${affiliateId}`, `/a/${affiliateId}`);
  if (!d) notFound();
  return <PortalView d={d} back={<Link href="/a" className="eyebrow hover:text-fg">← Programs</Link>} />;
}
