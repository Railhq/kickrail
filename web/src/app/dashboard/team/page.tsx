import { inviteMember, removeMember, revokeInvite } from "@/app/actions";
import { ActionForm, Submit } from "@/components/ActionForm";
import { Badge, Card, Table } from "@/components/ui";
import { api } from "@/lib/backend";
import { date } from "@/lib/format";
import { getMe } from "@/lib/me";

export const metadata = { title: "Team" };

type Team = { owner_id: string; members: { id: string; name: string; email: string; owner: boolean }[]; invites: { id: string; email: string; created_at: string; expires_at: string }[] };

export default async function TeamPage() {
  const [t, me] = await Promise.all([api<Team>("/merchant/team"), getMe("/dashboard/team")]);
  const isOwner = me.user.id === t.owner_id;
  return (
    <div className="space-y-6">
      <h1 className="page-title">Team</h1>
      <p className="text-sm text-muted">Everyone on the team can run the program: approve affiliates, record payouts, change settings. Only the owner can remove people and download tax IDs.</p>
      <Card title="Members">
        <Table head={["Name", "Email", ""]}>
          {t.members.map((u) => (
            <tr key={u.id}>
              <td className="px-5 py-3 font-medium">{u.name} {u.owner && <Badge tone="green">owner</Badge>} {u.id === me.user.id && <span className="text-xs text-muted">(you)</span>}</td>
              <td className="px-5 py-3 text-muted">{u.email}</td>
              <td className="px-5 py-3 text-right">
                {!u.owner && (isOwner || u.id === me.user.id) && (
                  <form action={removeMember.bind(null, u.id)}><button className="btn btn-danger">{u.id === me.user.id ? "Leave" : "Remove"}</button></form>
                )}
              </td>
            </tr>
          ))}
        </Table>
      </Card>
      <Card title="Invite someone">
        <ActionForm action={inviteMember} className="flex flex-wrap gap-2">
          <input className="input max-w-sm" name="email" type="email" placeholder="teammate@company.com" required aria-label="Email" />
          <Submit>Send invite</Submit>
        </ActionForm>
        <p className="mt-2 text-xs text-muted">The link works for 7 days, and only when they sign in with that email.</p>
        {t.invites.length > 0 && (
          <ul className="mt-5 divide-y divide-line border-t border-line text-sm">
            {t.invites.map((i) => (
              <li key={i.id} className="flex items-center justify-between gap-3 py-2.5">
                <span>{i.email} <span className="text-xs text-muted">invited {date(i.created_at)}, expires {date(i.expires_at)}</span></span>
                <form action={revokeInvite.bind(null, i.id)}><button className="text-xs text-red-700 hover:underline">revoke</button></form>
              </li>
            ))}
          </ul>
        )}
      </Card>
    </div>
  );
}
