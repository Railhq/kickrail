"use client";

import { connectStripe, disconnectStripe, rotateSecret, startStripeOAuth } from "@/app/actions";
import { ActionForm, Submit } from "@/components/ActionForm";

export function ConnectStripeButton({ connected }: { connected: boolean }) {
  return (
    <ActionForm action={startStripeOAuth}>
      <Submit variant={connected ? "secondary" : "primary"}>{connected ? "Reconnect with Stripe" : "Connect with Stripe"}</Submit>
    </ActionForm>
  );
}

export function ConnectStripeForm({ connected }: { connected: boolean }) {
  return (
    <ActionForm action={connectStripe} className="space-y-3">
      <input className="input font-mono" name="restricted_key" placeholder="rk_live_…" autoComplete="off" required />
      <Submit variant="secondary">{connected ? "Replace key" : "Connect with a key"}</Submit>
    </ActionForm>
  );
}

export function DisconnectStripe() {
  return (
    <ActionForm action={disconnectStripe}>
      <Submit variant="danger">Disconnect</Submit>
    </ActionForm>
  );
}

export function RotateSecret() {
  return (
    <ActionForm action={rotateSecret} secretLabel="New server API key">
      <Submit variant="secondary">Roll key</Submit>
    </ActionForm>
  );
}
