"use client";

import { useState, useTransition } from "react";
import { deleteRecord } from "@/app/actions";

export function DeleteButton({ kind, id, confirmText }: { kind: "referrals" | "commissions"; id: string; confirmText: string }) {
  const [pending, start] = useTransition();
  const [error, setError] = useState<string | null>(null);
  return (
    <div className="text-right">
      <button
        type="button"
        className="btn btn-secondary text-red-700"
        disabled={pending}
        onClick={() => {
          const reason = window.prompt(confirmText, "");
          if (reason === null) return;
          start(async () => {
            const r = await deleteRecord(kind, id, reason);
            setError(r?.error ?? null);
          });
        }}
      >
        {pending ? "Deleting…" : "Delete"}
      </button>
      {error && <p className="mt-1 max-w-xs text-xs text-red-600">{error}</p>}
    </div>
  );
}
