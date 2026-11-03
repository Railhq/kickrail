"use client";

// Proof of work for the sign-up and reset forms, checked by Railhq accounts (its
// backend/app/pow.py; static/pow.js is the same solver for its own pages). A person's
// browser solves it in about a second while they type; a script that only posts the form
// never gets an account or makes us email a stranger.

import { useCallback, useEffect, useRef } from "react";

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

/** Starts solving when the form mounts; `answer()` resolves to the `pow` field to send
 * (empty if it failed, and the server then says to reload). Each answer works once, so
 * call `answer()` once per submit. */
export function usePow(): () => Promise<string> {
  const job = useRef<{ at: number; p: Promise<string> } | null>(null);
  const start = useCallback(() => {
    job.current = { at: Date.now(), p: railhqPow().catch(() => "") };
  }, []);
  useEffect(() => {
    if (!job.current) start();
  }, [start]);
  return useCallback(async () => {
    if (!job.current || Date.now() - job.current.at > STALE_MS) start();
    const p = job.current!.p;
    start(); // the next submit (after an error) needs a fresh answer
    return p;
  }, [start]);
}
