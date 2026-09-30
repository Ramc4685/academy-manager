"use client";

import Link from "next/link";

import type { AdminStudentWaiverRow } from "@/lib/api/admin";
import { Chip, type ChipVariant } from "@/components/ds/chip";
import { Overline } from "@/components/ds/typography";
import { studentWaiverSummary, unsignedStudentWaivers } from "@/lib/admin/waiver-assignment";

import { formatDate } from "./format";

/**
 * Warning under the summary strip when a required waiver is not signed at its
 * live version. It is information for staff only: it never blocks enrollment
 * (Settings overhaul decision 9).
 */
export function StudentWaiverWarning({ rows }: { rows: ReadonlyArray<AdminStudentWaiverRow> }) {
  const unsigned = unsignedStudentWaivers(rows);
  if (unsigned.length === 0) return null;
  return (
    <div
      role="status"
      data-testid="admin-student-waiver-warning"
      className="rounded-lg border border-status-amber-200 bg-status-amber-50 px-4 py-3 text-sm text-status-amber-800"
    >
      <span className="font-semibold">Waiver not signed:</span>{" "}
      {unsigned.map((row) => row.title).join(", ")}. This does not block enrollment.
    </div>
  );
}

const STATE_CHIP: Record<AdminStudentWaiverRow["status"], { variant: ChipVariant; label: string }> = {
  signed: { variant: "approved", label: "SIGNED" },
  older_version: { variant: "pending", label: "OLDER VERSION" },
  unsigned: { variant: "pending", label: "NOT SIGNED" },
};

/** One row per waiver that applies to the student through their classes. */
export function StudentWaiversPanel({
  rows,
  loading,
  error,
}: {
  rows: ReadonlyArray<AdminStudentWaiverRow>;
  loading: boolean;
  error: boolean;
}) {
  return (
    <div data-testid="admin-student-waivers" className="mt-4">
      <Overline>Waivers for this student&apos;s classes</Overline>
      {loading ? (
        <p className="mt-2 text-sm text-rally-subtle">Loading waivers...</p>
      ) : error ? (
        <p role="alert" className="mt-2 text-sm text-red-700">
          Could not load waivers.
        </p>
      ) : rows.length === 0 ? (
        <p className="mt-2 text-sm text-rally-subtle" data-testid="admin-student-waivers-empty">
          No waiver is required for this student&apos;s classes.
        </p>
      ) : (
        <ul className="mt-2 divide-y divide-neutral-100">
          {rows.map((row) => {
            const chip = STATE_CHIP[row.status];
            return (
              <li
                key={row.waiver_template_id}
                data-testid={`admin-student-waiver-${row.waiver_template_id}`}
                className="flex flex-wrap items-center justify-between gap-2 py-3"
              >
                <div className="min-w-0">
                  <div className="text-sm font-semibold text-rally-ink">
                    {row.title}
                    {row.version && (
                      <span className="ml-2 font-mono text-[11px] font-normal text-rally-subtle">
                        v{row.version}
                      </span>
                    )}
                  </div>
                  <div className="mt-0.5 text-[12px] text-rally-muted">
                    {studentWaiverSummary(row)}
                    {row.signed_at ? ` · ${formatDate(row.signed_at)}` : ""}
                  </div>
                </div>
                <div className="flex items-center gap-3">
                  <Chip variant={chip.variant} label={chip.label} />
                  {row.signature_id && (
                    <Link
                      href={`/admin/waivers/signatures/${encodeURIComponent(row.signature_id)}`}
                      className="text-sm font-semibold text-rally-cobalt hover:underline"
                    >
                      View signature
                    </Link>
                  )}
                </div>
              </li>
            );
          })}
        </ul>
      )}
    </div>
  );
}
