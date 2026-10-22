"use client";

import { useRef, useState } from "react";
import type { StoredFile } from "@/lib/types";

/** Sends the file as the raw request body to /api/merchant/files and hands back where it lives. */
export async function uploadFile(file: File, kind: "asset" | "logo" | "favicon"): Promise<StoredFile> {
  const qs = new URLSearchParams({ kind, name: file.name });
  const res = await fetch(`/api/merchant/files?${qs}`, { method: "POST", body: file, headers: { "content-type": file.type || "application/octet-stream" } });
  const body = await res.json().catch(() => ({}));
  if (!res.ok) throw new Error(typeof body.detail === "string" ? body.detail : "Upload failed");
  return body as StoredFile;
}

export function UploadButton({ kind, accept, label = "Upload", onDone }: { kind: "asset" | "logo" | "favicon"; accept?: string; label?: string; onDone: (f: StoredFile) => void }) {
  const input = useRef<HTMLInputElement>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  return (
    <span className="inline-flex flex-col">
      <button type="button" className="btn btn-secondary" disabled={busy} onClick={() => input.current?.click()}>{busy ? "Uploading…" : label}</button>
      <input
        ref={input}
        type="file"
        accept={accept}
        className="hidden"
        onChange={async (e) => {
          const file = e.target.files?.[0];
          e.target.value = "";
          if (!file) return;
          setBusy(true);
          setError(null);
          try {
            onDone(await uploadFile(file, kind));
          } catch (err) {
            setError(err instanceof Error ? err.message : "Upload failed");
          } finally {
            setBusy(false);
          }
        }}
      />
      {error && <span className="mt-1 max-w-xs text-xs text-red-600">{error}</span>}
    </span>
  );
}

/** A URL field with an upload button next to it, for the logo and favicon. */
export function ImageUrlField({ name, kind, defaultValue, placeholder }: { name: string; kind: "logo" | "favicon"; defaultValue: string; placeholder: string }) {
  const [value, setValue] = useState(defaultValue);
  return (
    <div className="flex items-start gap-2">
      {value && (
        // eslint-disable-next-line @next/next/no-img-element
        <img src={value} alt="" className="h-9 w-9 shrink-0 rounded-lg border border-line bg-surface object-contain p-1" />
      )}
      <input className="input min-w-0 flex-1" name={name} type="url" value={value} onChange={(e) => setValue(e.target.value)} placeholder={placeholder} />
      <UploadButton kind={kind} accept="image/png,image/jpeg,image/gif,image/webp,image/svg+xml,image/x-icon" onDone={(f) => setValue(f.url)} />
      {value && <button type="button" className="btn btn-secondary" onClick={() => setValue("")} title="Remove">×</button>}
    </div>
  );
}
