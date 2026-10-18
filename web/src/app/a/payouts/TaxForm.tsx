"use client";

import { useState } from "react";
import { saveTaxInfo } from "@/app/actions";
import { ActionForm, Submit } from "@/components/ActionForm";
import { Field } from "@/components/ui";

export type TaxInfo = {
  form: "w9" | "w8ben" | "w8bene";
  legal_name: string;
  business_name?: string;
  classification?: string;
  country: string;
  address: string;
  date_of_birth?: string | null;
  treaty_country?: string | null;
  signature: string;
  signed_at: string;
  tin_last4: string;
};

const CLASSES: [string, string][] = [
  ["individual", "Individual / sole proprietor"],
  ["llc", "LLC"],
  ["c_corp", "C corporation"],
  ["s_corp", "S corporation"],
  ["partnership", "Partnership"],
  ["trust", "Trust / estate"],
  ["other", "Other"],
];

/** W-9 for US persons, W-8BEN for individuals elsewhere, W-8BEN-E for foreign entities. Signing again replaces the form. */
export function TaxForm({ current }: { current: TaxInfo | null }) {
  const [form, setForm] = useState<TaxInfo["form"]>(current?.form ?? "w9");
  const w9 = form === "w9";
  return (
    <ActionForm action={saveTaxInfo} className="space-y-4">
      <div className="flex flex-wrap gap-2">
        {([["w9", "W-9", "US citizen, resident or company"], ["w8ben", "W-8BEN", "Individual outside the US"], ["w8bene", "W-8BEN-E", "Company outside the US"]] as const).map(([v, label, hint]) => (
          <label key={v} className={`flex-1 cursor-pointer rounded-xl border px-3 py-2 text-sm ${form === v ? "border-ink bg-sunk/60" : "border-line"}`}>
            <input type="radio" name="form" value={v} checked={form === v} onChange={() => setForm(v)} className="sr-only" />
            <span className="font-medium">{label}</span>
            <span className="block text-xs text-muted">{hint}</span>
          </label>
        ))}
      </div>
      <div className="grid gap-4 sm:grid-cols-2">
        <Field label={form === "w8bene" ? "Organisation name" : "Legal name"}><input className="input" name="legal_name" defaultValue={current?.legal_name} required minLength={2} maxLength={120} /></Field>
        {w9 && <Field label="Business name" hint="If different from above."><input className="input" name="business_name" defaultValue={current?.business_name} maxLength={120} /></Field>}
        {w9 && (
          <Field label="Federal tax classification">
            <select className="input" name="classification" defaultValue={current?.classification ?? "individual"}>
              {CLASSES.map(([v, l]) => <option key={v} value={v}>{l}</option>)}
            </select>
          </Field>
        )}
        {!w9 && (
          <Field label={form === "w8ben" ? "Country of citizenship" : "Country of organisation"} hint="Two-letter code, like GB or IN.">
            <input className="input uppercase" name="country" defaultValue={current?.form !== "w9" ? current?.country : ""} pattern="[A-Za-z]{2}" maxLength={2} required />
          </Field>
        )}
        <Field label={w9 ? "SSN or EIN" : "Foreign tax ID"} hint={current ? `On file: •••${current.tin_last4}. Enter it again to re-sign.` : "Stored encrypted. Programs only see the last four digits."}>
          <input className="input font-mono" name="tin" required minLength={4} maxLength={40} autoComplete="off" />
        </Field>
        {form === "w8ben" && <Field label="Date of birth"><input className="input" name="date_of_birth" type="date" defaultValue={current?.date_of_birth ?? ""} /></Field>}
        {!w9 && <Field label="Treaty country" hint="Optional: to claim reduced withholding."><input className="input uppercase" name="treaty_country" defaultValue={current?.treaty_country ?? ""} pattern="[A-Za-z]{2}" maxLength={2} /></Field>}
        <div className="sm:col-span-2"><Field label="Address"><textarea className="input min-h-16" name="address" defaultValue={current?.address} required minLength={5} maxLength={400} /></Field></div>
      </div>
      <label className="flex items-start gap-2 text-sm">
        <input type="checkbox" name="certify" required className="mt-1" />
        <span>
          Under penalties of perjury, I certify that the information on this form is true, correct and complete
          {w9 ? ", that the number shown is my correct taxpayer identification number, and that I am a U.S. person." : ", and that I am not a U.S. person."}
        </span>
      </label>
      <Field label="Signature" hint="Type your full name."><input className="input max-w-sm" name="signature" required minLength={2} maxLength={120} /></Field>
      <Submit>{current ? "Sign again" : "Sign and save"}</Submit>
    </ActionForm>
  );
}
