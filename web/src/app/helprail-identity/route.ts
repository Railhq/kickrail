import { createHmac } from "node:crypto";
import { NextResponse } from "next/server";
import { api } from "@/lib/backend";
import { getSession } from "@/lib/session";

export const dynamic = "force-dynamic";

type Me = { user?: { id?: string; email?: string; name?: string; created_at?: string | null }; plan?: unknown; workspace?: { plan?: unknown } | null };

function planOf(me: Me): string | undefined {
  for (const p of [me.workspace?.plan, me.plan]) {
    if (typeof p === "string") return p;
    if (p && typeof p === "object") {
      const o = p as { id?: unknown; name?: unknown };
      if (typeof o.id === "string") return o.id;
      if (typeof o.name === "string") return o.name;
    }
  }
}

/**
 * Who the Helprail support chat should say this visitor is. Off unless HELPRAIL_WORKSPACE and
 * HELPRAIL_IDENTITY_SECRET are set. A signed-in user gets their email signed with the
 * workspace's identity secret (which never leaves the server), so their conversations follow
 * them across devices and nobody can open someone else's by typing an email. Everyone else
 * chats anonymously.
 */
export async function GET() {
  const workspace = process.env.HELPRAIL_WORKSPACE;
  const secret = process.env.HELPRAIL_IDENTITY_SECRET;
  const headers = { "cache-control": "private, no-store" };
  if (!workspace || !secret) return NextResponse.json({ enabled: false }, { headers });
  const url = (process.env.HELPRAIL_URL || "https://app.helprail.io").replace(/\/$/, "");

  let user = null;
  if (await getSession()) {
    const me = await api<Me>("/auth/me").catch(() => null);
    const email = me?.user?.email?.trim().toLowerCase();
    if (email) {
      const attrs: Record<string, string> = {};
      const plan = planOf(me!);
      if (plan) attrs.plan = plan;
      if (me!.user!.created_at) attrs.signed_up_at = String(me!.user!.created_at);
      user = {
        user_id: email,
        user_hash: createHmac("sha256", secret).update(email).digest("hex"),
        email,
        name: me!.user!.name || undefined,
        attrs,
      };
    }
  }
  return NextResponse.json({ enabled: true, url, workspace, user }, { headers });
}
