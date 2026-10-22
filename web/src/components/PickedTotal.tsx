"use client";

import { useEffect, useState } from "react";
import { money } from "@/lib/format";

const boxes = (form: string) => Array.from(document.querySelectorAll<HTMLInputElement>(`input[form="${form}"][name="commission_ids"]:not(:disabled)`));

/** "Select all" and the running total of the commissions ticked for a form. */
export function PickedTotal({ form }: { form: string }) {
  const [picked, setPicked] = useState<HTMLInputElement[]>([]);
  useEffect(() => {
    const update = () => setPicked(boxes(form).filter((b) => b.checked));
    document.addEventListener("change", update);
    return () => document.removeEventListener("change", update);
  }, [form]);
  const totals: Record<string, number> = {};
  for (const b of picked) totals[b.dataset.currency!] = (totals[b.dataset.currency!] ?? 0) + Number(b.dataset.cents);
  const all = picked.length > 0 && picked.length === boxes(form).length;
  return (
    <div className="flex flex-wrap items-center gap-3 text-sm">
      <button
        type="button"
        className="btn btn-secondary"
        onClick={() => {
          const list = boxes(form);
          for (const b of list) b.checked = !all;
          setPicked(all ? [] : list);
        }}
      >
        {all ? "Clear" : "Select all on this page"}
      </button>
      <span className="text-muted">
        {picked.length ? <>{picked.length} picked · <b className="text-fg">{Object.entries(totals).map(([c, v]) => money(v, c)).join(" + ")}</b></> : "Tick the commissions you paid."}
      </span>
    </div>
  );
}
