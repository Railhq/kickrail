"use client";

// Pathrail analytics (pathrail.io, our own). The tag goes in the root layout's <head>; the
// stub queues calls made before script.js loads. PathrailUser sits in the signed-in shell:
// it identifies the person once per browser session, and counts a sign-up the first time
// it sees an account made in the last 15 minutes, whichever way it was made (email form,
// Railhq or Google).

import { useEffect } from "react";

const STUB = "window.pathrail=window.pathrail||function(){(pathrail.q=pathrail.q||[]).push(arguments)}";
const NEW_MS = 15 * 60 * 1000;

declare global {
  interface Window {
    pathrail?: (...args: unknown[]) => void;
  }
}

/** `skip` is a path regex for pages that aren't ours to count, and `host` limits counting to our
 * own domain (partner portals also run on customers' domains). */
export function PathrailTag({ site, skip, host }: { site: string; skip?: string; host?: string }) {
  if (!skip && !host) {
    return (
      <>
        <script dangerouslySetInnerHTML={{ __html: STUB }} />
        <script defer data-site={site} src="https://pathrail.io/js/script.js" />
      </>
    );
  }
  const load = `${STUB};if(${host ? `(location.hostname==${JSON.stringify(host)}||location.hostname.endsWith(${JSON.stringify("." + host)}))&&` : ""}!new RegExp(${JSON.stringify(skip ?? "^$")}).test(location.pathname)){var s=document.createElement("script");s.defer=true;s.src="https://pathrail.io/js/script.js";s.setAttribute("data-site",${JSON.stringify(site)});document.head.appendChild(s)}`;
  return <script dangerouslySetInnerHTML={{ __html: load }} />;
}

const once = (store: Storage | undefined, key: string) => {
  try {
    if (!store || store.getItem(key)) return false;
    store.setItem(key, "1");
    return true;
  } catch {
    return false;
  }
};

export function PathrailUser({ user }: { user: { id: string; email: string; created_at?: string | null } }) {
  useEffect(() => {
    const pr = window.pathrail;
    if (!pr) return;
    if (once(window.sessionStorage, `pr_id:${user.id}`)) pr("identify", { email: user.email, user_id: user.id });
    const made = user.created_at ? Date.parse(user.created_at.endsWith("Z") || /[+-]\d\d:\d\d$/.test(user.created_at) ? user.created_at : user.created_at + "Z") : NaN;
    if (Date.now() - made < NEW_MS && once(window.localStorage, `pr_signup:${user.id}`)) pr("signup");
  }, [user.id, user.email, user.created_at]);
  return null;
}
