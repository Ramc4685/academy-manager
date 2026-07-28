"use client";

/**
 * Tenant (academy) switcher.
 *
 * Renders the user's active-academy chip in the admin topbar. When the
 * user has more than one membership, the chip becomes a dropdown that
 * lets them switch the active academy. Selection updates `TenantContext`
 * and persists to localStorage (`X-Academy-Id` is stamped onto every v2
 * request by `lib/api/client.ts`).
 *
 * Per ADR-0007 the server is the source of truth for tenant resolution.
 * This switcher is a UX convenience for multi-academy admins and never
 * grants tenant access on its own.
 */

import { useCallback, useEffect, useRef, useState } from "react";
import Link from "next/link";
import { useQuery } from "@tanstack/react-query";

import { getAdminAcademy } from "@/lib/api/admin";
import { useTenant } from "@/lib/tenant/tenant-context";
import type { AcademyMembershipSummary } from "@/lib/api/v2/memberships";
import { queryKeys } from "@/lib/query/keys";

export function TenantSwitcher() {
  const { status, memberships, activeAcademyId, switchAcademy } = useTenant();
  const [open, setOpen] = useState(false);
  const containerRef = useRef<HTMLDivElement | null>(null);
  const academyQuery = useQuery({
    queryKey: queryKeys.admin.academy(),
    queryFn: getAdminAcademy,
  });

  // Close on outside click + Escape.
  useEffect(() => {
    if (!open) return;
    const onDocClick = (e: MouseEvent) => {
      if (containerRef.current && !containerRef.current.contains(e.target as Node)) {
        setOpen(false);
      }
    };
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") setOpen(false);
    };
    document.addEventListener("mousedown", onDocClick);
    document.addEventListener("keydown", onKey);
    return () => {
      document.removeEventListener("mousedown", onDocClick);
      document.removeEventListener("keydown", onKey);
    };
  }, [open]);

  const handleSelect = useCallback(
    (academyId: string) => {
      switchAcademy(academyId);
      setOpen(false);
    },
    [switchAcademy],
  );

  if (status === "loading") {
    return (
      <div
        className="font-mono text-[10px] font-bold tracking-overline rounded-md border border-rally-line bg-white/60 px-2.5 py-1 text-rally-muted"
        data-testid="tenant-switcher-loading"
        aria-live="polite"
      >
        Academy
      </div>
    );
  }

  if (status === "error" || memberships.length === 0) {
    return (
      <div
        className="font-mono text-[10px] font-bold tracking-overline rounded-md border border-amber-200 bg-amber-50 px-2.5 py-1 text-amber-800"
        data-testid="tenant-switcher-empty"
        role="status"
      >
        Academy
      </div>
    );
  }

  const label = displayAcademyName(academyQuery.data?.display_name);
  const single = memberships.length === 1;
  // The rollup only says anything a single academy dashboard does not when
  // the user owns more than one.
  const ownsMultipleAcademies =
    memberships.filter((m) => m.roles?.includes("owner")).length > 1;

  if (single) {
    return (
      <div
        className="text-[12px] font-semibold rounded-md border border-rally-line bg-white px-2.5 py-1 text-rally-ink truncate max-w-[220px]"
        data-testid="tenant-switcher-single"
        title={label}
      >
        {label}
      </div>
    );
  }

  return (
    <div ref={containerRef} className="relative">
      <button
        type="button"
        data-testid="tenant-switcher-button"
        aria-haspopup="listbox"
        aria-expanded={open}
        aria-label="Switch academy"
        onClick={() => setOpen((v) => !v)}
        className="text-[12px] font-semibold rounded-md border border-rally-line bg-white px-2.5 py-1 text-rally-ink hover:bg-neutral-50 focus:outline-none focus:ring-2 focus:ring-rally-cobalt-600 inline-flex items-center gap-1.5 max-w-[220px]"
      >
        <span className="truncate">{label}</span>
        <Chevron open={open} />
      </button>
      {open && (
        <ul
          role="listbox"
          aria-label="Available academies"
          data-testid="tenant-switcher-menu"
          className="absolute right-0 mt-1 w-64 rounded-md border border-rally-line bg-white shadow-lg z-40 py-1 max-h-80 overflow-y-auto"
        >
          {ownsMultipleAcademies && (
            <li role="option" aria-selected={false} className="border-b border-rally-line">
              <Link
                href="/owner"
                data-testid="tenant-switcher-all-academies"
                onClick={() => setOpen(false)}
                className="block px-3 py-2 text-sm hover:bg-neutral-50 focus:bg-neutral-100 focus:outline-none"
              >
                <span className="font-medium text-rally-cobalt-600">All academies</span>
                <div className="font-mono text-[10px] text-rally-muted mt-0.5">
                  FRANCHISE ROLLUP
                </div>
              </Link>
            </li>
          )}
          {memberships.map((m) => {
            const selected = m.academy_id === activeAcademyId;
            return (
              <li key={m.academy_id} role="option" aria-selected={selected}>
                <button
                  type="button"
                  data-testid={`tenant-switcher-option-${m.academy_id}`}
                  onClick={() => handleSelect(m.academy_id)}
                  className={`w-full text-left px-3 py-2 text-sm hover:bg-neutral-50 focus:bg-neutral-100 focus:outline-none ${
                    selected ? "bg-neutral-50" : ""
                  }`}
                >
                  <div className="flex items-center justify-between gap-2">
                    <span className="font-medium text-rally-ink truncate">{m.academy_name}</span>
                    {selected && (
                      <span
                        className="font-mono text-[9px] font-bold tracking-overline text-rally-cobalt-600"
                        aria-hidden="true"
                      >
                        ACTIVE
                      </span>
                    )}
                  </div>
                  <div className="font-mono text-[10px] text-rally-muted mt-0.5">
                    {renderRoles(m)}
                  </div>
                </button>
              </li>
            );
          })}
        </ul>
      )}
    </div>
  );
}

function displayAcademyName(name: string | null | undefined): string {
  const trimmed = name?.trim();
  return trimmed || "Academy";
}

function renderRoles(m: AcademyMembershipSummary): string {
  if (!m.roles || m.roles.length === 0) return "—";
  return m.roles.map((r) => r.toUpperCase()).join(" · ");
}

function Chevron({ open }: { open: boolean }) {
  return (
    <svg
      aria-hidden="true"
      width="10"
      height="10"
      viewBox="0 0 10 10"
      className={`transition-transform ${open ? "rotate-180" : ""}`}
    >
      <path d="M1 3 L5 7 L9 3" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round" />
    </svg>
  );
}
