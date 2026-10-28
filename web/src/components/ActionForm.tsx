"use client";

import { useActionState } from "react";
import { useFormStatus } from "react-dom";
import type { State } from "@/app/actions";
import { CopyButton } from "./CopyButton";

export function ActionForm({
  action,
  children,
  className,
  id,
  secretLabel = "Secret key",
}: {
  action: (prev: State, f: FormData) => Promise<State>;
  children: React.ReactNode;
  className?: string;
  id?: string;
  secretLabel?: string;
}) {
  const [state, run] = useActionState(action, null);
  return (
    <form action={run} className={className} id={id}>
      {children}
      {state?.error && <p className="mt-3 text-sm text-red-600">{state.error}</p>}
      {state?.ok && <p className="mt-3 text-sm text-emerald-700">{state.ok}</p>}
      {state?.ok && state.href && <a className="btn btn-primary mt-3 w-full" href={state.href}>Continue</a>}
      {state?.secret && (
        <div className="mt-4 rounded-lg border border-amber-300 bg-amber-50 p-3 text-sm">
          <p className="font-medium text-amber-900">{secretLabel}. Copy it now: it won&apos;t be shown again.</p>
          <div className="mt-2 flex items-center gap-2">
            <code className="flex-1 break-all rounded bg-white px-2 py-1 font-mono text-xs">{state.secret}</code>
            <CopyButton text={state.secret} />
          </div>
        </div>
      )}
    </form>
  );
}

export function Submit({ children, variant = "primary", className = "" }: { children: React.ReactNode; variant?: "primary" | "secondary" | "danger"; className?: string }) {
  const { pending } = useFormStatus();
  return (
    <button type="submit" disabled={pending} className={`btn btn-${variant} ${className}`}>
      {pending ? "Working…" : children}
    </button>
  );
}
