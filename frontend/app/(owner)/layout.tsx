"use client";

/**
 * Owner (franchise) route group.
 *
 * Access is not a persona check: ownership is per-membership, so the shell
 * only requires an authenticated session and lets `GET /owner/rollup` be the
 * authority — it 404s for anyone who owns no academies, and when the
 * `enable_owner_role` flag is off.
 */

import Link from "next/link";

import { PersonaLogoutButton } from "@/components/persona/logout-button";
import { ShuttleMark } from "@/components/ds/shuttle";

export default function OwnerLayout({ children }: { children: React.ReactNode }) {
  return (
    <div className="min-h-screen bg-rally-paper">
      <header className="border-b border-rally-line bg-white">
        <div className="mx-auto flex max-w-6xl items-center justify-between gap-3 px-4 py-3">
          <div className="flex items-center gap-2">
            <ShuttleMark />
            <span className="font-mono text-[10px] font-bold tracking-overline text-rally-muted">
              FRANCHISE
            </span>
          </div>
          <div className="flex items-center gap-3">
            <Link
              href="/admin"
              className="text-[12px] font-semibold text-rally-cobalt-600 hover:underline"
            >
              Back to academy
            </Link>
            <PersonaLogoutButton />
          </div>
        </div>
      </header>
      <main className="mx-auto max-w-6xl px-4 py-6">{children}</main>
    </div>
  );
}
