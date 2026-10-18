import { Badge, Card, Empty, Notice, Table } from "@/components/ui";
import { api } from "@/lib/backend";
import { date } from "@/lib/format";

export const metadata = { title: "Emails" };

type Email = { id: string; kind: string; to: string; subject: string; text: string; status: "logged" | "pending" | "sent" | "failed"; last_error?: string; sent_at?: string; created_at: string };

const TONE = { sent: "green", logged: "gray", pending: "amber", failed: "red" } as const;

export default async function EmailsPage() {
  const { smtp_configured, emails } = await api<{ smtp_configured: boolean; emails: Email[] }>("/merchant/emails");
  return (
    <div className="space-y-6">
      <h1 className="page-title">Emails</h1>
      {!smtp_configured && (
        <Notice>No mail server is configured, so emails are recorded here as <b>logged</b> and not delivered. Set <code>KR_BREVO_API_KEY</code> or <code>KR_SMTP_HOST</code> on the backend to send them. Addresses at example.com are always only logged.</Notice>
      )}
      <Card title="Last 200">
        {emails.length === 0 ? (
          <Empty>No emails yet. Welcome, approval, commission and payout emails show up here. Turn kinds on or off in Settings.</Empty>
        ) : (
          <Table head={["When", "To", "Subject", "Status"]}>
            {emails.map((e) => (
              <tr key={e.id}>
                <td className="whitespace-nowrap px-5 py-3 text-muted">{date(e.created_at)}</td>
                <td className="px-5 py-3">{e.to}<p className="text-xs text-muted">{e.kind.replace("_", " ")}</p></td>
                <td className="px-5 py-3">
                  <details>
                    <summary className="cursor-pointer">{e.subject}</summary>
                    <pre className="mt-2 max-w-xl whitespace-pre-wrap rounded-lg bg-sunk/60 p-3 font-sans text-xs leading-relaxed">{e.text}</pre>
                  </details>
                </td>
                <td className="px-5 py-3"><Badge tone={TONE[e.status] ?? "gray"}>{e.status}</Badge>{e.last_error && <p className="mt-1 text-xs text-red-700">{e.last_error}</p>}</td>
              </tr>
            ))}
          </Table>
        )}
      </Card>
    </div>
  );
}
