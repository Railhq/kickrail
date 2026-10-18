"use client";

import { useState } from "react";

type T = "campaign" | "percent" | "flat" | "none";

/** Percent / flat / nothing picker, posted as rate_type + percent | flat + currency. */
export function RateFields({
  defaultType,
  defaultPercent,
  defaultFlat,
  defaultCurrency,
  withCampaign = false,
  prefix = "",
}: {
  defaultType: T;
  defaultPercent: number;
  defaultFlat: number;
  defaultCurrency: string;
  withCampaign?: boolean;
  prefix?: string;
}) {
  const [type, setType] = useState<T>(defaultType);
  return (
    <div className="flex flex-wrap gap-2">
      <select className="input w-44" name={`${prefix}rate_type`} value={type} onChange={(e) => setType(e.target.value as T)}>
        {withCampaign && <option value="campaign">Campaign rate</option>}
        <option value="percent">Percent</option>
        <option value="flat">Flat amount</option>
        <option value="none">No commission</option>
      </select>
      {type === "percent" && (
        <div className="relative w-28">
          <input className="input pr-8" name={`${prefix}percent`} type="number" step="0.01" min="0.01" max="100" defaultValue={defaultPercent} required />
          <span className="absolute right-3 top-2 text-sm text-muted">%</span>
        </div>
      )}
      {type === "flat" && (
        <>
          <input className="input w-28" name={`${prefix}flat`} type="number" step="0.01" min="0.01" defaultValue={defaultFlat} required />
          <input className="input w-20 uppercase" name={`${prefix}currency`} defaultValue={defaultCurrency} maxLength={3} />
        </>
      )}
    </div>
  );
}
