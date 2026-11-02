import { redirect } from "next/navigation";
import { maybe } from "@/lib/backend";
import { JoinView, joinMetadata, load } from "../JoinView";

export async function generateMetadata({ params }: { params: Promise<{ slug: string }> }) {
  return joinMetadata(await load((await params).slug));
}

export default async function Join({ params }: { params: Promise<{ slug: string }> }) {
  const p = await load((await params).slug);
  // An affiliate already in this program, signed in here, goes straight to their portal page.
  // Anything going wrong here just shows the join page.
  const mine = await maybe<{ programs: { affiliate_id: string; program: { slug: string } }[] }>("/portal").catch(() => null);
  const joined = mine?.programs.find((x) => x.program.slug === p.slug);
  if (joined) redirect(`/a/${joined.affiliate_id}`);
  return <JoinView p={p} />;
}
