"use client";

import { useEffect, useRef, useState } from "react";
import { saveTerms } from "@/app/actions";
import { ActionForm, Submit } from "@/components/ActionForm";
import { Field } from "@/components/ui";

// execCommand is old but still the one zero-dependency way to edit rich text in every
// browser. Whatever it produces is cleaned to an allowlist on the server.
const TOOLS: [string, string, string, string?][] = [
  ["P", "Paragraph", "formatBlock", "p"],
  ["H", "Heading", "formatBlock", "h3"],
  ["B", "Bold", "bold"],
  ["I", "Italic", "italic"],
  ["•", "Bulleted list", "insertUnorderedList"],
  ["1.", "Numbered list", "insertOrderedList"],
  ["↶", "Undo", "undo"],
  ["↷", "Redo", "redo"],
];

export function TermsEditor({ title, html, externalUrl }: { title: string; html: string; externalUrl: string }) {
  const editor = useRef<HTMLDivElement>(null);
  const [value, setValue] = useState(html);
  // Filled once: React must not own the editable content, or each re-render would reset it.
  useEffect(() => {
    if (editor.current) editor.current.innerHTML = html;
    document.execCommand("defaultParagraphSeparator", false, "p");
  }, [html]);
  const run = (cmd: string, arg?: string) => {
    editor.current?.focus();
    document.execCommand(cmd, false, arg);
    setValue(editor.current?.innerHTML ?? "");
  };
  return (
    <ActionForm action={saveTerms} className="space-y-4">
      <Field label="Title"><input className="input" name="title" maxLength={120} defaultValue={title} /></Field>
      <div>
        <p className="mb-1.5 text-sm font-medium">Content</p>
        <div className="overflow-hidden rounded-xl border border-line">
          <div className="flex flex-wrap gap-1 border-b border-line bg-sunk/50 p-1.5">
            {TOOLS.map(([icon, label, cmd, arg]) => (
              <button key={label} type="button" title={label} aria-label={label} className="min-w-8 rounded-md px-2 py-1 text-sm hover:bg-surface" onMouseDown={(e) => e.preventDefault()} onClick={() => run(cmd, arg)}>
                <span className={cmd === "bold" ? "font-bold" : cmd === "italic" ? "italic" : ""}>{icon}</span>
              </button>
            ))}
            <button
              type="button"
              title="Link"
              aria-label="Link"
              className="rounded-md px-2 py-1 text-sm underline hover:bg-surface"
              onMouseDown={(e) => e.preventDefault()}
              onClick={() => {
                const url = window.prompt("Link to (https://…)", "https://");
                if (url && /^(https?:\/\/|mailto:)/.test(url)) run("createLink", url);
              }}
            >
              link
            </button>
          </div>
          <div
            ref={editor}
            contentEditable
            suppressContentEditableWarning
            role="textbox"
            aria-multiline="true"
            aria-label="Terms content"
            className="prose-terms min-h-72 p-4 text-sm leading-relaxed outline-none"
            onInput={(e) => setValue(e.currentTarget.innerHTML)}
          />
        </div>
        <input type="hidden" name="html" value={value} />
        <p className="mt-1.5 text-xs text-muted">Leave it empty to remove the hosted page.</p>
      </div>
      <Field label="External URL" hint="Link to a terms page on your own website instead. When set, the join page and portal link there rather than to the page above.">
        <input className="input" name="external_url" type="url" defaultValue={externalUrl} placeholder="https://…/affiliate-terms" />
      </Field>
      <Submit>Save terms</Submit>
    </ActionForm>
  );
}
