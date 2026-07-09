"use client";

/**
 * Persona (view) switcher.
 *
 * Shown only when the current user holds two or more roles. Lists the
 * personas the user holds and navigates to that persona's home route.
 * General across all role combinations (admin/coach/parent).
 */

import { useEffect, useRef, useState } from "react";
import { useRouter } from "next/navigation";
import { useQuery } from "@tanstack/react-query";

import { getCurrentUser, type UserRole } from "@/lib/api/me";

const PERSONA_HOME: Record<UserRole, string> = {
  admin: "/admin",
  coach: "/coach/today",
  parent: "/parent/payments",
};

const PERSONA_LABEL: Record<UserRole, string> = {
  admin: "Admin view",
  coach: "Coach view",
  parent: "Parent view",
};

const PERSONA_ORDER: UserRole[] = ["admin", "coach", "parent"];

export function PersonaSwitcher({
  current,
  variant = "light",
}: {
  current: UserRole;
  variant?: "light" | "dark";
}) {
  const router = useRouter();
  const [open, setOpen] = useState(false);
  const containerRef = useRef<HTMLDivElement | null>(null);
  const meQuery = useQuery({ queryKey: ["me", "persona-switcher"], queryFn: getCurrentUser });

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

  const roles = PERSONA_ORDER.filter((r) => meQuery.data?.roles.includes(r));
  if (roles.length < 2) return null;

  const buttonClasses =
    variant === "dark"
      ? "text-[12px] font-semibold rounded-md border border-white/20 bg-white/10 px-2.5 py-1 text-white hover:bg-white/20 focus:outline-none focus:ring-2 focus:ring-white/40 inline-flex items-center gap-1.5"
      : "text-[12px] font-semibold rounded-md border border-rally-line bg-white px-2.5 py-1 text-rally-ink hover:bg-neutral-50 focus:outline-none focus:ring-2 focus:ring-rally-cobalt-600 inline-flex items-center gap-1.5";

  return (
    <div ref={containerRef} className="relative">
      <button
        type="button"
        data-testid="persona-switcher-button"
        aria-haspopup="listbox"
        aria-expanded={open}
        aria-label="Switch view"
        onClick={() => setOpen((v) => !v)}
        className={buttonClasses}
      >
        <span>{PERSONA_LABEL[current]}</span>
        <span aria-hidden="true">{open ? "▴" : "▾"}</span>
      </button>
      {open && (
        <ul
          role="listbox"
          aria-label="Available views"
          data-testid="persona-switcher-menu"
          className="absolute right-0 mt-1 w-44 rounded-md border border-rally-line bg-white shadow-lg z-40 py-1"
        >
          {roles.map((role) => (
            <li key={role}>
              <button
                type="button"
                role="option"
                aria-selected={role === current}
                data-testid={`persona-switcher-option-${role}`}
                onClick={() => {
                  setOpen(false);
                  if (role !== current) router.push(PERSONA_HOME[role]);
                }}
                className={`w-full px-3 py-2 text-left text-[13px] hover:bg-neutral-50 ${
                  role === current ? "font-semibold text-rally-ink" : "text-slate-600"
                }`}
              >
                {PERSONA_LABEL[role]}
              </button>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}
