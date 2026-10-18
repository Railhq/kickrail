import Link from "next/link";
import { redirect } from "next/navigation";
import { Card } from "@/components/ui";
import { api, ApiError } from "@/lib/backend";

export const metadata = { title: "Connecting Stripe" };

// Stripe sends the merchant back here after they approve (or decline) Kickrail.
export default async function StripeCallback({ searchParams }: { searchParams: Promise<Record<string, string | undefined>> }) {
  const { code, state, error, error_description } = await searchParams;
  let message = error_description || (error ? "Stripe didn't connect." : "");
  if (code && state) {
    try {
      await api("/merchant/stripe/oauth", { body: { code, state } });
    } catch (e) {
      if (!(e instanceof ApiError)) throw e;
      message = e.message;
    }
    if (!message) redirect("/dashboard/settings#stripe");
  }
  return (
    <div className="mx-auto max-w-lg">
      <Card title="Stripe isn't connected">
        <p className="text-sm text-muted">{message || "Something went wrong on the way back from Stripe."}</p>
        <p className="mt-4 text-sm"><Link className="link" href="/dashboard/settings#stripe">Back to Settings</Link></p>
      </Card>
    </div>
  );
}
