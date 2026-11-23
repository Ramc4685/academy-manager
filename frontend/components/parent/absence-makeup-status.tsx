"use client";

import type { Route } from "next";
import Link from "next/link";

import { Chip } from "@/components/ds/chip";
import type { AbsenceMakeupView } from "@/lib/api/parent";
import { absenceMakeupDisplay } from "@/lib/parent-requests";

/**
 * A reported absence's makeup state (Reported / Makeup eligible / requested /
 * booked / expired), as the server decided it. An eligible makeup links
 * straight to the Makeups tab with this class pre-selected.
 */
export function AbsenceMakeupStatus({
  makeup,
  studentId,
  occurrenceId,
  academyTimezone,
}: {
  makeup: AbsenceMakeupView | null | undefined;
  studentId: string;
  occurrenceId: string;
  academyTimezone: string | null;
}) {
  // No state from the server (lookup failed, older response): show nothing
  // rather than guess "Reported".
  if (!makeup) return null;
  const display = absenceMakeupDisplay(makeup, { studentId, occurrenceId }, academyTimezone);
  return (
    <div data-testid={`absence-makeup-${studentId}-${occurrenceId}`} className="mt-2 space-y-1">
      <Chip variant={display.chip} label={display.label.toUpperCase()} />
      {display.detail && <p className="text-xs text-status-slate-600 break-words">{display.detail}</p>}
      {display.bookHref && (
        <Link
          href={display.bookHref as Route}
          className="inline-flex min-h-touch items-center text-sm font-semibold text-rally-cobalt-600 underline underline-offset-2"
        >
          Book a makeup
        </Link>
      )}
    </div>
  );
}
