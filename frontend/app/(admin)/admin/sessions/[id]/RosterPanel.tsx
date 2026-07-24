"use client";

import Link from "next/link";
import { useQuery } from "@tanstack/react-query";

import {
  listEnrollmentEvents,
  type AdminEnrollmentView,
  type EnrollmentStatus,
} from "@/lib/api/admin";
import { type Level } from "@/lib/api/curriculum";
import { buildStudentProgressHref } from "@/lib/navigation/admin-student-progress-return";

import { Avatar } from "@/components/ds/avatar";
import { Button } from "@/components/ds/button";
import { Chip, type ChipVariant } from "@/components/ds/chip";
import { Th } from "@/components/ds/dialog-chrome";

import { actionCellClass, actionHeaderClass, formatDateOnly, formatEnrollmentDate, formatLifecycleType } from "./format";

const ENROLL_CHIP: Record<EnrollmentStatus, { variant: ChipVariant; label: string }> = {
  active: { variant: "enrolled", label: "ACTIVE" },
  paused: { variant: "paused", label: "PAUSED" },
  cancelled: { variant: "expired", label: "CANCELLED" },
  withdrawn: { variant: "expired", label: "WITHDRAWN" },
};

export function RosterMetrics({
  enrollments,
  capacity,
}: {
  enrollments: AdminEnrollmentView[];
  capacity: number;
}) {
  const filled = enrollments.length;
  const openSpots = Math.max(capacity - filled, 0);
  const dueCount = enrollments.filter((e) => e.dues_status === "due").length;
  const overdueCount = enrollments.filter((e) => e.dues_status === "overdue").length;
  const numericLevels = enrollments
    .map((e) => e.pathway_level_sequence)
    .filter((level): level is number => Number.isInteger(level));
  const levelText =
    numericLevels.length === 0
      ? "No levels"
      : `${Math.min(...numericLevels)}-${Math.max(...numericLevels)}`;

  return (
    <div className="mb-4 grid grid-cols-1 gap-2 sm:grid-cols-2 2xl:grid-cols-4">
      <RosterMetric label="In session" value={String(filled)} />
      <RosterMetric
        label="Open spots"
        value={String(openSpots)}
        detail={openSpots > 0 ? `Add ${openSpots}` : "Full"}
        tone={openSpots > 0 ? "open" : "full"}
      />
      <RosterMetric
        label="Fee follow-up"
        value={String(dueCount + overdueCount)}
        detail={overdueCount > 0 ? `${overdueCount} overdue` : dueCount > 0 ? `${dueCount} due` : "Clear"}
        tone={overdueCount > 0 ? "danger" : dueCount > 0 ? "warn" : "open"}
      />
      <RosterMetric label="Pathway levels" value={levelText} detail="Skill Pathway" />
    </div>
  );
}

export function RosterMetric({
  label,
  value,
  detail,
  tone = "neutral",
}: {
  label: string;
  value: string;
  detail?: string;
  tone?: "neutral" | "open" | "warn" | "danger" | "full";
}) {
  const toneClass =
    tone === "danger"
      ? "border-red-200 bg-red-50 text-red-900"
      : tone === "warn"
        ? "border-amber-200 bg-amber-50 text-amber-900"
        : tone === "open"
          ? "border-emerald-200 bg-emerald-50 text-emerald-900"
          : tone === "full"
            ? "border-rally-line bg-rally-paper text-rally-ink"
            : "border-rally-line bg-white text-rally-ink";
  return (
    <div className={`min-w-0 rounded-md border px-3 py-2 ${toneClass}`}>
      <p className="font-mono text-[10px] font-bold uppercase tracking-overline opacity-70">
        {label}
      </p>
      <p className="mt-1 font-display text-lg font-semibold">{value}</p>
      {detail && <p className="text-xs opacity-75">{detail}</p>}
    </div>
  );
}

export function RosterTable({
  enrollments,
  sessionId,
  pathwayLevels,
  updatingPlacementStudentId,
  onPathwayLevelChange,
  onDelete,
  onPause,
  onResume,
  onTransfer,
  onWithdraw,
}: {
  enrollments: AdminEnrollmentView[];
  sessionId: string;
  pathwayLevels: Level[];
  updatingPlacementStudentId: string | null;
  onPathwayLevelChange: (enrollment: AdminEnrollmentView, levelId: string) => void;
  onDelete: (enrollment: AdminEnrollmentView) => void;
  onPause: (enrollment: AdminEnrollmentView) => void;
  onResume: (id: string) => void;
  onTransfer: (enrollment: AdminEnrollmentView) => void;
  onWithdraw: (enrollment: AdminEnrollmentView) => void;
}) {
  return (
    <div className="overflow-x-auto">
      <table className="w-full min-w-[1040px] text-sm">
        <thead>
          <tr className="border-b border-rally-line text-left">
            <Th>Name</Th>
            <Th>Pathway Level</Th>
            <Th>Status</Th>
            <Th>Fees</Th>
            <Th>Enrolled</Th>
            <Th className={actionHeaderClass}><span className="sr-only">Actions</span></Th>
          </tr>
        </thead>
        <tbody>
          {enrollments.map((e) => {
            const chip = ENROLL_CHIP[e.status];
            const rowToneClass =
              e.dues_status === "overdue"
                ? "bg-red-50/60"
                : e.dues_status === "due"
                  ? "bg-amber-50/60"
                  : "bg-white";
            return (
              <tr
                key={e.enrollment_id}
                data-testid={`enrollment-row-${e.enrollment_id}`}
                className={`border-b border-rally-line/60 last:border-0 ${rowToneClass}`}
              >
                <td className="px-4 py-3">
                  <div className="flex min-w-0 items-center gap-2">
                    <Avatar name={e.full_name} size={28} />
                    <span className="min-w-0 font-display font-semibold text-rally-ink">
                      {e.full_name}
                    </span>
                  </div>
                </td>
                <td className="px-4 py-3">
                  <LevelSelect
                    value={e.pathway_level_id ?? ""}
                    levels={pathwayLevels}
                    disabled={
                      updatingPlacementStudentId === e.student_id ||
                      !e.pathway_program_id ||
                      pathwayLevels.length === 0
                    }
                    onChange={(levelId) => onPathwayLevelChange(e, levelId)}
                  />
                  <p className="mt-1 text-[11px] text-rally-muted">
                    {e.pathway_level_name ? (
                      <Link
                        href={
                          `/admin/sessions/${sessionId}/skill-board${
                            e.pathway_program_id
                              ? `?program_id=${encodeURIComponent(e.pathway_program_id)}`
                              : ""
                          }` as Parameters<typeof Link>[0]["href"]
                        }
                        className="text-xs text-blue-600 underline-offset-2 hover:underline"
                      >
                        {e.pathway_skills_completed ?? 0}/{e.pathway_skills_total ?? 0} skills
                      </Link>
                    ) : (
                      "Placement needed"
                    )}
                  </p>
                </td>
                <td className="px-4 py-3">
                  <Chip variant={chip.variant} label={chip.label} />
                </td>
                <td className="px-4 py-3">
                  <DuesChip status={e.dues_status ?? "current"} />
                </td>
                <td className="px-4 py-3 font-mono text-rally-muted">
                  {formatEnrollmentDate(e.enrolled_at)}
                  <EnrollmentHistory enrollmentId={e.enrollment_id} />
                </td>
                <td className={`${actionCellClass} ${rowToneClass}`}>
                  <div className="flex min-w-[262px] flex-wrap items-center justify-end gap-1.5">
                    {e.status === "active" ? (
                      <Button variant="secondary" size="sm" onClick={() => onPause(e)}>
                        Pause
                      </Button>
                    ) : e.status === "paused" ? (
                      <Button variant="secondary" size="sm" onClick={() => onResume(e.enrollment_id)}>
                        Resume
                      </Button>
                    ) : null}
                    <Button variant="secondary" size="sm" onClick={() => onTransfer(e)}>
                      Move
                    </Button>
                    <Link
                      href={buildStudentProgressHref({
                        studentId: e.student_id,
                        programId: e.pathway_program_id,
                        returnTo: `/admin/sessions/${encodeURIComponent(sessionId)}`,
                        returnLabel: "Back to session",
                      }) as Parameters<typeof Link>[0]["href"]}
                      className="inline-flex min-h-9 items-center justify-center rounded-md border border-rally-line bg-white px-3 py-1.5 text-sm font-semibold text-rally-ink shadow-sm transition-colors hover:bg-neutral-50"
                    >
                      Pathway
                    </Link>
                    {e.status === "active" && (
                      <Button variant="secondary" size="sm" onClick={() => onWithdraw(e)}>
                        Withdraw
                      </Button>
                    )}
                    <Button
                      variant="danger"
                      size="sm"
                      onClick={() => onDelete(e)}
                      aria-label={`Remove ${e.full_name}`}
                    >
                      Remove
                    </Button>
                  </div>
                </td>
              </tr>
            );
          })}
        </tbody>
      </table>
    </div>
  );
}

export function LevelSelect({
  value,
  levels,
  disabled,
  onChange,
}: {
  value: string;
  levels: Level[];
  disabled: boolean;
  onChange: (levelId: string) => void;
}) {
  return (
    <select
      value={value}
      disabled={disabled}
      onChange={(event) => {
        if (event.target.value) onChange(event.target.value);
      }}
      className="min-h-9 rounded-md border border-rally-line bg-white px-2 py-1 font-mono text-xs font-semibold text-rally-ink focus:outline-none focus:ring-2 focus:ring-rally-cobalt-600/30 disabled:opacity-60"
      aria-label="Student pathway level"
    >
      <option value="">Place</option>
      {levels.map((level) => (
        <option key={level.level_id} value={level.level_id}>
          L{level.sequence} · {level.name}
        </option>
      ))}
    </select>
  );
}

export function DuesChip({ status }: { status: "current" | "due" | "overdue" }) {
  if (status === "current") return <Chip variant="paid" label="CURRENT" />;
  if (status === "due") return <Chip variant="pending" label="DUE" />;
  return <Chip variant="overdue" label="OVERDUE" />;
}

export function EnrollmentHistory({ enrollmentId }: { enrollmentId: string }) {
  const eventsQuery = useQuery({
    queryKey: ["admin", "enrollment-events", enrollmentId],
    queryFn: () => listEnrollmentEvents(enrollmentId),
    staleTime: 30_000,
  });
  const events = eventsQuery.data?.events ?? [];
  const latest = events.at(-1);
  if (!latest) {
    return null;
  }
  return (
    <div className="mt-1 text-[11px] font-normal text-rally-subtle">
      {formatLifecycleType(latest.event_type)} · {formatDateOnly(latest.effective_date)}
    </div>
  );
}
