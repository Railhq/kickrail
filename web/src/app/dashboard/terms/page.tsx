import { Card } from "@/components/ui";
import { api } from "@/lib/backend";
import { date } from "@/lib/format";
import type { Merchant } from "@/lib/types";
import { TermsEditor } from "./TermsEditor";

export const metadata = { title: "Terms" };

export default async function TermsPage() {
  const m = await api<Merchant>("/merchant");
  const hosted = `${m.portal_url}/join/${m.slug}/terms`;
  return (
    <div className="space-y-6">
      <h1 className="page-title">Terms of Service</h1>
      <p className="text-sm text-muted">
        The terms affiliates agree to when they join. They&apos;re linked from your join page and every affiliate&apos;s portal.
        {m.terms && <> Hosted at <a className="link" href={hosted} target="_blank" rel="noopener">{hosted.replace(/^https?:\/\//, "")}</a>, last saved {date(m.terms.updated_at)}.</>}
      </p>
      <Card>
        <TermsEditor title={m.terms?.title ?? "Terms of Service"} html={m.terms?.html ?? ""} externalUrl={m.branding.terms_url ?? ""} />
      </Card>
    </div>
  );
}
