import { JoinView, joinMetadata, load } from "../JoinView";

export async function generateMetadata({ params }: { params: Promise<{ slug: string }> }) {
  return joinMetadata(await load((await params).slug));
}

export default async function Join({ params }: { params: Promise<{ slug: string }> }) {
  return <JoinView p={await load((await params).slug)} />;
}
