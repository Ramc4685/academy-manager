"use client";

import { createContext, useContext } from "react";

/**
 * Owner scope for the admin shell, resolved once by the layout's
 * `usePersonaAuth("admin")` and shared with pages so they do not each re-run
 * the /me check. Defaults to `false`: a page rendered outside the provider
 * hides owner-only controls rather than leaking them.
 */
const OwnerContext = createContext<boolean>(false);

export function OwnerProvider({
  isOwner,
  children,
}: {
  isOwner: boolean;
  children: React.ReactNode;
}) {
  return <OwnerContext.Provider value={isOwner}>{children}</OwnerContext.Provider>;
}

/** True when the signed-in user holds the academy `owner` scope. */
export function useIsOwner(): boolean {
  return useContext(OwnerContext);
}

/**
 * Shown in place of an owner-only page (or panel) to an admin without the
 * owner scope. The BFF 404s their data for these routes, so this is the honest
 * state, not a security boundary.
 */
export function OwnerOnlyPanel() {
  return (
    <div
      data-testid="owner-only-panel"
      role="status"
      className="rounded-xl border border-rally-line bg-white p-6 text-sm text-rally-muted"
    >
      <div className="font-mono text-[10px] font-bold uppercase tracking-overline text-rally-muted">
        Owner only
      </div>
      <p className="mt-2 text-rally-ink">
        This page is for the academy owner. Ask them if you need a change here.
      </p>
    </div>
  );
}

/** One-line hint standing in for a hidden owner-only action. */
export function OwnerOnlyHint({ className = "" }: { className?: string }) {
  return (
    <span
      data-testid="owner-only-hint"
      className={`font-mono text-[10px] font-bold uppercase tracking-overline text-rally-subtle ${className}`}
      title="Only the academy owner can do this"
    >
      Owner only
    </span>
  );
}

/**
 * Note under a money field an admin can see but not change (Settings overhaul
 * Phase 1 PR 5): prices, fees and the academy timezone are owner-only. The
 * BFF refuses a changed value with a 403; this says so before they try.
 */
export function OwnerOnlyFieldNote({ id, className = "" }: { id?: string; className?: string }) {
  return (
    <span
      id={id}
      data-testid="owner-only-field-note"
      className={`flex items-center gap-2 text-xs font-normal text-rally-muted ${className}`}
    >
      <OwnerOnlyHint />
      <span>Only the academy owner can change this.</span>
    </span>
  );
}
