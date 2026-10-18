import { JoinView, joinMetadata, load } from "../../JoinView";

type Params = { params: Promise<{ slug: string; campaign: string }> };

export async function generateMetadata({ params }: Params) {
  const { slug, campaign } = await params;
  return joinMetadata(await load(slug, campaign));
}

export default async function JoinCampaign({ params }: Params) {
  const { slug, campaign } = await params;
  return <JoinView p={await load(slug, campaign)} />;
}
