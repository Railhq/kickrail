"use client";

// Proof of work for the sign-up and reset forms, checked by Railhq accounts (its
// backend/app/pow.py; static/pow.js is the same solver for its own pages). A person's
// browser solves it in about a second while they type; a script that only posts the form
// never gets an account or makes us email a stranger.

import { createElement, useCallback, useEffect, useRef } from "react";

const POW_URL = process.env.NEXT_PUBLIC_RAILHQ_POW_URL || "https://accounts.getrailhq.com/api/pow";
const STALE_MS = 15 * 60 * 1000; // challenges last 20 minutes

type Challenge = { algorithm: string; challenge: string; salt: string; maxnumber: number; signature: string };

const hex = (buf: ArrayBuffer) => Array.from(new Uint8Array(buf), (b) => b.toString(16).padStart(2, "0")).join("");

async function solve(c: Challenge): Promise<string> {
  const enc = new TextEncoder();
  for (let start = 0; start <= c.maxnumber; start += 1000) {
    const ns: number[] = [];
    for (let n = start; n < Math.min(start + 1000, c.maxnumber + 1); n++) ns.push(n);
    const hs = await Promise.all(ns.map((n) => crypto.subtle.digest("SHA-256", enc.encode(c.salt + n))));
    const i = hs.findIndex((h) => hex(h) === c.challenge);
    if (i >= 0) return btoa(JSON.stringify({ algorithm: c.algorithm, challenge: c.challenge, number: ns[i], salt: c.salt, signature: c.signature }));
  }
  throw new Error("no answer");
}

export async function railhqPow(): Promise<string> {
  const r = await fetch(POW_URL, { cache: "no-store" });
  if (!r.ok) throw new Error("no challenge");
  return solve(await r.json());
}

// A text field people never see or reach. Bots that fill in every input fill it too, and
// their submit then sends "trap", which the server refuses (and counts) like a missing answer.
const TRAP = "rh_extra";
const hidden = { position: "absolute", left: "-10000px", width: 1, height: 1, overflow: "hidden" } as const;

/** Put inside each form that sends `pow`. */
export function PowTrap() {
  return createElement("input", { type: "text", name: TRAP, tabIndex: -1, autoComplete: "off", "aria-hidden": true, defaultValue: "", style: hidden });
}

/** Starts solving when the form mounts; `answer(form)` resolves to the `pow` field to send
 * (empty if it failed, and the server then says to reload) and takes the trap field out of
 * the form data. Each answer works once, so call `answer()` once per submit. */
export function usePow(): (f?: FormData) => Promise<string> {
  const job = useRef<{ at: number; p: Promise<string> } | null>(null);
  const start = useCallback(() => {
    job.current = { at: Date.now(), p: railhqPow().catch(() => "") };
  }, []);
  useEffect(() => {
    if (!job.current) start();
  }, [start]);
  return useCallback(async (f?: FormData) => {
    const trapped = String(f?.get(TRAP) ?? "") !== "";
    f?.delete(TRAP);
    if (trapped) return "trap";
    if (!job.current || Date.now() - job.current.at > STALE_MS) start();
    const p = job.current!.p;
    start(); // the next submit (after an error) needs a fresh answer
    return p;
  }, [start]);
}
