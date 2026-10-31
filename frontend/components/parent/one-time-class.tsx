"use client";

import { Chip } from "@/components/ds/chip";
import type { AssignedClassView } from "@/lib/api/parent";
import { assignedClassCopy } from "@/lib/parent-requests";
import { scheduleSourceLabel } from "@/lib/parent/schedule-events";

/**
 * Badge for a one-time class on the parent schedule (#1038). Renders nothing
 * for a regular class (or a payload without `source`). Make-ups are blue,
 * trials yellow, so colour alone tells them apart too.
 */
export function OneTimeClassChip({ source }: { source: string | null | undefined }) {
  const label = scheduleSourceLabel(source);
  if (!label) return null;
  return <Chip variant={source === "trial" ? "trial" : "makeup"} label={label.toUpperCase()} />;
}

/**
 * #1038: where and when an approved make-up / trial actually happens, so the
 * family is not left with a bare "APPROVED" chip.
 */
export function AssignedClassDetails({
  kind,
  assigned,
  academyTimezone,
}: {
  kind: "makeup" | "trial";
  assigned: AssignedClassView | null | undefined;
  academyTimezone: string | null;
}) {
  const copy = assignedClassCopy(assigned, academyTimezone);
  if (!copy) return null;
  return (
    <div
      data-testid="assigned-class"
      className="mt-2 rounded-lg bg-rally-cobalt-50 p-2 text-xs text-rally-ink"
    >
      <div className="flex flex-wrap items-center gap-1.5">
        <OneTimeClassChip source={kind} />
        <span className={copy.cancelled ? "font-semibold line-through" : "font-semibold"}>
          {copy.title}
        </span>
      </div>
      <p className="mt-1 text-status-slate-600">{copy.when}</p>
      <p className="text-status-slate-600">{copy.where}</p>
      {copy.cancelled && (
        <p className="mt-0.5 font-semibold text-status-red-800">
          Cancelled — this class will not run
        </p>
      )}
    </div>
  );
}
