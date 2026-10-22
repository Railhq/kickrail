"use client";

/** A form button that asks first. `action` is a server action already bound to its record. */
export function ConfirmButton({ action, confirmText, children, className = "btn btn-secondary" }: { action: () => Promise<void>; confirmText: string; children: React.ReactNode; className?: string }) {
  return (
    <form action={action} onSubmit={(e) => { if (!window.confirm(confirmText)) e.preventDefault(); }} className="inline">
      <button className={className}>{children}</button>
    </form>
  );
}
