"use client";

/**
 * Admin Inbox "Attendance" tab: class dates nobody took attendance for (past
 * the coach's 48h window) and marks changed or voided after the fact. Every
 * row links straight to that class date with its Attendance open.
 *
 * One list layout at every width: each row is already two short lines, so a
 * phone and a desktop read the same thing.
 */

import type { Route } from "next";
import { useQuery } from "@tanstack/react-query";

import {
  getAdminAttendanceReview,
  type AdminAttendanceCorrectionRow,
  type AdminMissingAttendanceRow,
} from "@/lib/api/admin";
import { formatAcademyDateTime } from "@/lib/format/academy-time";
import { queryKeys } from "@/lib/query/keys";
import { Card } from "@/components/ds/card";
import { Chip, type ChipVariant } from "@/components/ds/chip";
import { EmptyState } from "@/components/ds/empty-state";
import { PhoneList, PhoneListRow } from "@/components/ds/phone-row";
import { TableSkeleton } from "@/components/ds/skeleton";

const STATUS_LABEL: Record<string, string> = {
  present: "Present",
  absent: "Absent",
  late: "Late",
  voided: "Voided",
};

function statusVariant(status: string): ChipVariant {
  if (status === "present" || status === "absent" || status === "late") return status;
  return "denied";
}

function MissingRow({ row }: { row: AdminMissingAttendanceRow }) {
  return (
    <PhoneListRow
      data-testid={`admin-attendance-missing-${row.occurrence_id}`}
      title={row.session_name}
      href={row.href as Route}
      titleTestId={`admin-attendance-missing-link-${row.occurrence_id}`}
      primary={<Chip variant="pending" label="NOT MARKED" />}
      secondary={
        <>
          <div>{formatAcademyDateTime(row.start_at, null)}</div>
          <div>
            {row.enrolled_count} student{row.enrolled_count === 1 ? "" : "s"} on the roster, no
            marks
          </div>
        </>
      }
    />
  );
}

function CorrectionRow({ row }: { row: AdminAttendanceCorrectionRow }) {
  const from = row.previous_status ? (STATUS_LABEL[row.previous_status] ?? row.previous_status) : "—";
  return (
    <PhoneListRow
      data-testid={`admin-attendance-correction-${row.attendance_id}`}
      title={row.student_name}
      href={row.href as Route}
      titleTestId={`admin-attendance-correction-link-${row.attendance_id}`}
      primary={
        <Chip variant={statusVariant(row.status)} label={(STATUS_LABEL[row.status] ?? row.status).toUpperCase()} />
      }
      secondary={
        <>
          <div>
            {row.session_name}
            {row.start_at ? ` · ${formatAcademyDateTime(row.start_at, null)}` : ""}
          </div>
          <div>
            Was {from}. Changed {formatAcademyDateTime(row.corrected_at, null)}
            {row.corrected_by_name ? ` by ${row.corrected_by_name}` : ""}
          </div>
          {row.reason ? <div className="break-words">Reason: {row.reason}</div> : null}
        </>
      }
    />
  );
}

export function AttendanceTab() {
  const { data, isLoading, isError } = useQuery({
    queryKey: queryKeys.admin.inboxAttendance(),
    queryFn: getAdminAttendanceReview,
  });

  if (isError) {
    return (
      <p role="alert" className="rounded-md bg-red-50 p-3 text-sm text-red-700">
        Could not load attendance to review.
      </p>
    );
  }
  if (isLoading || !data) return <TableSkeleton rows={3} />;

  return (
    <div className="space-y-6" data-testid="admin-attendance-tab">
      <section aria-labelledby="admin-attendance-missing-heading" className="space-y-2">
        <div>
          <h2 id="admin-attendance-missing-heading" className="font-display text-lg font-bold text-rally-ink">
            Not marked
          </h2>
          <p className="text-sm text-rally-subtle">
            Classes from the last 30 days with students on the roster and no attendance, once the
            coach&apos;s 48-hour window has passed.
          </p>
        </div>
        {data.missing.length === 0 ? (
          <EmptyState title="Every recent class date has attendance." data-testid="admin-attendance-missing-empty" compact />
        ) : (
          <Card p={0}>
            <PhoneList aria-label="Class dates with no attendance" data-testid="admin-attendance-missing-list">
              {data.missing.map((row) => (
                <MissingRow key={row.occurrence_id} row={row} />
              ))}
            </PhoneList>
          </Card>
        )}
      </section>

      <section aria-labelledby="admin-attendance-corrections-heading" className="space-y-2">
        <div>
          <h2 id="admin-attendance-corrections-heading" className="font-display text-lg font-bold text-rally-ink">
            Corrected or voided
          </h2>
          <p className="text-sm text-rally-subtle">Marks changed after they were recorded, last 14 days.</p>
        </div>
        {data.corrections.length === 0 ? (
          <EmptyState title="No attendance corrections." data-testid="admin-attendance-corrections-empty" compact />
        ) : (
          <Card p={0}>
            <PhoneList aria-label="Attendance corrections" data-testid="admin-attendance-corrections-list">
              {data.corrections.map((row) => (
                <CorrectionRow key={row.attendance_id} row={row} />
              ))}
            </PhoneList>
          </Card>
        )}
      </section>
    </div>
  );
}
