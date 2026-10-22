"use client";

import { useState } from "react";
import { createAsset, updateAsset } from "@/app/actions";
import { ActionForm, Submit } from "@/components/ActionForm";
import { Field } from "@/components/ui";
import { UploadButton } from "@/components/Upload";
import { fileSize } from "@/lib/format";
import type { Asset, AssetType, StoredFile } from "@/lib/types";

const TYPES: [AssetType, string, string][] = [
  ["image", "Image", "Logos, banners, screenshots"],
  ["file", "File", "A PDF, media kit or zip to download"],
  ["link", "Link", "A page on your site; affiliates get it with their own link"],
  ["text", "Copy", "Text to paste; {link} and {code} become the affiliate's own"],
];

export function NewAsset() {
  const [type, setType] = useState<AssetType>("image");
  const [file, setFile] = useState<StoredFile | null>(null);
  return (
    <ActionForm action={createAsset} className="space-y-4">
      <div className="grid gap-2 sm:grid-cols-4">
        {TYPES.map(([t, label, hint]) => (
          <label key={t} className={`cursor-pointer rounded-xl border p-3 text-sm ${type === t ? "border-fg bg-sunk/60" : "border-line"}`}>
            <input type="radio" name="type" value={t} checked={type === t} onChange={() => { setType(t); setFile(null); }} className="sr-only" />
            <span className="font-medium">{label}</span>
            <span className="mt-0.5 block text-xs text-muted">{hint}</span>
          </label>
        ))}
      </div>
      {(type === "image" || type === "file") && (
        <div className="flex flex-wrap items-center gap-3">
          <input type="hidden" name="file_id" value={file?.id ?? ""} />
          <UploadButton kind="asset" accept={type === "image" ? "image/*" : undefined} label={file ? "Replace file" : type === "image" ? "Choose image" : "Choose file"} onDone={setFile} />
          {file ? <span className="text-sm">{file.name} <span className="text-muted">{fileSize(file.size)}</span></span> : <span className="text-sm text-muted">Up to 10 MB.</span>}
          {file && type === "image" && (
            // eslint-disable-next-line @next/next/no-img-element
            <img src={file.url} alt="" className="h-12 max-w-32 rounded border border-line object-contain" />
          )}
        </div>
      )}
      <div className="grid gap-4 sm:grid-cols-2">
        <Field label="Name"><input className="input" name="name" required maxLength={120} defaultValue={file?.name ?? ""} key={file?.id ?? type} /></Field>
        <Field label="Description" hint="Optional. Tell affiliates where it works best."><input className="input" name="description" maxLength={1000} /></Field>
        {type === "link" && <div className="sm:col-span-2"><Field label="URL" hint="Links to your own site get the affiliate's tracking added; other links are shown as they are."><input className="input" name="url" type="url" required placeholder="https://…" /></Field></div>}
        {type === "text" && <div className="sm:col-span-2"><Field label="Text" hint="{link} and {code} are replaced with each affiliate's own link and code."><textarea className="input min-h-24" name="text" required maxLength={5000} placeholder="I use this every day. Try it with my link: {link}" /></Field></div>}
      </div>
      <div className="flex flex-wrap gap-2">
        <button name="status" value="published" className="btn btn-primary">Publish</button>
        <Submit variant="secondary">Save as draft</Submit>
      </div>
    </ActionForm>
  );
}

export function EditAsset({ a }: { a: Asset }) {
  return (
    <details>
      <summary className="cursor-pointer text-xs text-muted">Edit</summary>
      <ActionForm action={updateAsset.bind(null, a.id)} className="mt-3 grid gap-3">
        <input className="input" name="name" required maxLength={120} defaultValue={a.name} aria-label="Name" />
        <input className="input" name="description" maxLength={1000} defaultValue={a.description} placeholder="Description" aria-label="Description" />
        {a.type === "link" && <input className="input" name="url" type="url" required defaultValue={a.url ?? ""} aria-label="URL" />}
        {a.type === "text" && <textarea className="input min-h-24" name="text" required maxLength={5000} defaultValue={a.text ?? ""} aria-label="Text" />}
        <div><Submit variant="secondary">Save</Submit></div>
      </ActionForm>
    </details>
  );
}
