"use client";

import { useEffect, useMemo, useState } from "react";
import { useMutation, useQuery } from "@tanstack/react-query";

import {
  addSessionReplacement,
  cancelSessionOccurrence,
  listAdminUsers,
  listOccurrenceStudentAttendance,
  voidOccurrenceStudentAttendance,
  setSessionAssistants,
  updateAdminSession,
  updateSessionOccurrenceReplacement,
  type AdminSessionOccurrenceView,
  type AdminSessionView,
  type AdminStudentAttendanceView,
  type AdminUserView,
  type EditSessionRequest,
} from "@/lib/api/admin";
import { roleLabel } from "@/lib/admin/role-label";
import { queryKeys } from "@/lib/query/keys";

import { Button } from "@/components/ds/button";
import { PhoneList, PhoneListRow } from "@/components/ds/phone-row";
import { useIsPhone } from "@/lib/use-is-phone";
import {
  DialogActions,
  DialogError,
  Field,
  RallyModal as RallyDialog,
  Th,
} from "@/components/ds/dialog-chrome";

import { CoachSelect, DaySelect } from "./dialogs";
import {
  actionCellClass,
  actionHeaderClass,
  blankToNull,
  buildEditSessionForm,
  centsToDollarsInput,
  dateInputValueFromOffset,
  dollarsInputToCents,
  hasRecurringSchedule,
  inputClass,
  looksLikeWebUrl,
  looksLikeWhatsAppGroupInvite,
  sessionDateLabel,
  toDateInputValue,
  todayDateInput,
} from "./format";
import {
  parseAcademyInstant,
  resolveAcademyTimeZone,
} from "@/lib/format/academy-time";

/**
 * A date the server will refuse to cancel (#671).
 *
 * `assert_occurrence_cancellable` rejects any occurrence whose `start_at` has
 * passed and any `completed` one, so offering the action there only ever
 * produces a raw 409 in the dialog. Module-level, not computed in the
 * component body: reading the clock during render is impure.
 */
function hasStarted(occurrence: AdminSessionOccurrenceView): boolean {
  return parseAcademyInstant(occurrence.start_at).getTime() <= Date.now();
}

function isCancellable(occurrence: AdminSessionOccurrenceView): boolean {
  return occurrence.status === "scheduled" && !hasStarted(occurrence);
}

export function ReplacementCoachTable({
  occurrences,
  userNameById,
  timezone,
  onEdit,
  onCancel,
  onViewAttendance,
  showStatus = false,
  emptyLabel,
}: {
  occurrences: AdminSessionOccurrenceView[];
  userNameById: Map<string, string>;
  /** The parent session's IANA zone; occurrence instants render in it. */
  timezone: string | null;
  onEdit: (occurrence: AdminSessionOccurrenceView) => void;
  /**
   * Issue #671. When given, each still-scheduled FUTURE date offers "Cancel
   * this date". Past and completed dates never do: the domain guard
   * (`assert_occurrence_cancellable`) refuses any occurrence whose `start_at`
   * has passed, so offering the button there only ever produces a raw 409 in
   * the dialog for an action that was never possible.
   */
  onCancel?: (occurrence: AdminSessionOccurrenceView) => void;
  /**
   * Issue #554. When given, a date whose attendance was taken offers
   * "Attendance", which opens the per-student marks with a Void action.
   */
  onViewAttendance?: (occurrence: AdminSessionOccurrenceView) => void;
  /** Show the Cancelled chip column (#671). */
  showStatus?: boolean;
  emptyLabel?: string;
}) {
  // Occurrence start/end are UTC instants. Formatting them without an explicit
  // timeZone renders the viewer's browser zone, which shows the wrong hour for
  // anyone outside the academy's zone.
  const { timeZone } = resolveAcademyTimeZone(timezone);
  const isPhone = useIsPhone();
  const coachLabel = (coachId: string | null | undefined, fallback: string) =>
    coachId ? (userNameById.get(coachId) ?? fallback) : "-";

  const dateLabel = (occurrence: AdminSessionOccurrenceView) =>
    parseAcademyInstant(occurrence.start_at).toLocaleDateString("en-US", {
      month: "short",
      day: "numeric",
      timeZone,
    });
  const timeLabel = (occurrence: AdminSessionOccurrenceView) =>
    `${parseAcademyInstant(occurrence.start_at).toLocaleTimeString("en-US", {
      hour: "numeric",
      minute: "2-digit",
      timeZone,
    })} - ${parseAcademyInstant(occurrence.end_at).toLocaleTimeString("en-US", {
      hour: "numeric",
      minute: "2-digit",
      timeZone,
    })}`;

  function statusNode(occurrence: AdminSessionOccurrenceView) {
    if (occurrence.status === "cancelled") {
      return (
        <span
          data-testid="occurrence-cancelled-chip"
          title={occurrence.cancellation_reason ?? undefined}
          className="inline-flex items-center rounded-full bg-rally-line px-2 py-0.5 text-xs font-medium text-rally-muted"
        >
          Cancelled
        </span>
      );
    }
    if (occurrence.status === "completed") {
      return <span className="text-xs text-rally-subtle">Completed</span>;
    }
    // A date that ran but was never marked completed still reads "scheduled"
    // in the database; calling it Scheduled here is what made an admin try to
    // cancel last week.
    if (hasStarted(occurrence)) return <span className="text-xs text-rally-subtle">Past</span>;
    return <span className="text-xs text-rally-subtle">Scheduled</span>;
  }

  /**
   * #857: the three date actions stay DIRECT buttons on the phone row rather
   * than moving into the row menu. `cancel-occurrence-<id>` and
   * `attendance-occurrence-<id>` are clicked by id in
   * `admin-cancel-class-date.spec.ts`, and a menu item carries no
   * `data-testid` — behind a menu those specs would resolve nothing under
   * chromium-mobile. Each is given the 44px the acceptance bar asks for
   * instead, stacked full width.
   */
  function dateActions(occurrence: AdminSessionOccurrenceView, phone: boolean) {
    const buttonClass = phone ? "min-h-touch w-full justify-center" : undefined;
    return (
      <div
        className={
          phone
            ? "flex flex-col gap-2 pt-1"
            : "flex max-w-[168px] flex-wrap justify-end gap-2 sm:max-w-none"
        }
      >
        <Button
          variant="secondary"
          size="sm"
          className={buttonClass}
          onClick={() => onEdit(occurrence)}
        >
          Change replacement
        </Button>
        {onCancel && isCancellable(occurrence) && (
          <Button
            variant="secondary"
            size="sm"
            className={buttonClass}
            data-testid={`cancel-occurrence-${occurrence.occurrence_id}`}
            onClick={() => onCancel(occurrence)}
          >
            Cancel this date
          </Button>
        )}
        {/* Issue #554: attendance can only be corrected or voided on a date
            that was actually marked, so the action only appears where there is
            something to act on. */}
        {onViewAttendance && occurrence.attendance_marked_count > 0 && (
          <Button
            variant="secondary"
            size="sm"
            className={buttonClass}
            data-testid={`attendance-occurrence-${occurrence.occurrence_id}`}
            onClick={() => onViewAttendance(occurrence)}
          >
            Attendance
          </Button>
        )}
      </div>
    );
  }

  if (isPhone) {
    /* #857: six columns over a 760px minimum with a `sticky right-0` action
       cell — on a phone the sticky cell covered the dates it belonged to, and
       each date's coaches and status were off-screen behind it. */
    return (
      <div>
        <PhoneList aria-label="Class dates" data-testid="admin-class-dates-phone-list">
          {occurrences.map((occurrence) => (
            <PhoneListRow
              key={occurrence.occurrence_id}
              data-testid={`class-date-row-${occurrence.occurrence_id}`}
              title={dateLabel(occurrence)}
              primary={showStatus ? statusNode(occurrence) : undefined}
              secondary={
                <>
                  <div className="font-mono">{timeLabel(occurrence)}</div>
                  <div>
                    {coachLabel(occurrence.scheduled_coach_id, "Scheduled coach")}
                    {occurrence.actual_coach_id
                      ? ` → ${coachLabel(occurrence.actual_coach_id, "Replacement coach")}`
                      : ""}
                  </div>
                  {dateActions(occurrence, true)}
                </>
              }
            />
          ))}
        </PhoneList>
        {occurrences.length === 0 && emptyLabel && (
          <p className="pt-2 text-sm text-rally-subtle">{emptyLabel}</p>
        )}
      </div>
    );
  }

  return (
    <div className="overflow-x-auto">
      <table className="w-full min-w-[760px] text-left text-sm">
        <thead>
          <tr className="border-b border-rally-line text-xs uppercase tracking-wide text-rally-muted">
            <Th>Date</Th>
            <Th>Time</Th>
            <Th>Scheduled coach</Th>
            <Th>Replacement coach</Th>
            {showStatus && <Th>Status</Th>}
            <Th className={actionHeaderClass}>Action</Th>
          </tr>
        </thead>
        <tbody>
          {occurrences.map((occurrence) => (
            <tr
              key={occurrence.occurrence_id}
              // #857: the same id the phone row carries, so a spec can count
              // class dates without knowing which layout is mounted.
              data-testid={`class-date-row-${occurrence.occurrence_id}`}
              className="border-b border-rally-line/60"
            >
              <td className="py-3 pr-4">
                <p className="font-medium text-rally-ink">{dateLabel(occurrence)}</p>
              </td>
              <td className="whitespace-nowrap py-3 pr-4 font-mono text-rally-muted">
                {timeLabel(occurrence)}
              </td>
              <td className="py-3 pr-4 text-rally-muted">
                {coachLabel(occurrence.scheduled_coach_id, "Scheduled coach")}
              </td>
              <td className="py-3 pr-4 text-rally-muted">
                {coachLabel(occurrence.actual_coach_id, "Replacement coach")}
              </td>
              {showStatus && <td className="py-3 pr-4">{statusNode(occurrence)}</td>}
              <td className={`${actionCellClass} bg-white`}>
                {/* Both buttons side by side are ~300px wide — on a tablet that
                    sticky cell covered the whole visible table. Capped so they
                    stack under 640px and sit in one row above it. */}
                {dateActions(occurrence, false)}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
      {occurrences.length === 0 && emptyLabel && (
        <p className="pt-2 text-sm text-rally-subtle">{emptyLabel}</p>
      )}
    </div>
  );
}

/**
 * "Cancel this date" (issue #671).
 *
 * A rain-out, a sick coach or a holiday calls off ONE class. The reason is
 * required because it reaches the families verbatim, and the copy states the
 * money consequence up front: everyone enrolled that month is credited the
 * date's share automatically, so an admin is never guessing whether they also
 * have to issue a refund by hand.
 */
export function CancelOccurrenceDialog({
  occurrence,
  timezone,
  onClose,
  onCancelled,
}: {
  occurrence: AdminSessionOccurrenceView | null;
  timezone: string | null;
  onClose: () => void;
  onCancelled: () => void;
}) {
  const [reason, setReason] = useState("");
  const [notify, setNotify] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const open = Boolean(occurrence);
  const { timeZone } = resolveAcademyTimeZone(timezone);

  useEffect(() => {
    if (!open) return;
    setReason("");
    setNotify(true);
    setError(null);
  }, [open, occurrence]);

  const mutation = useMutation({
    mutationFn: () => {
      if (!occurrence) throw new Error("No class date selected.");
      return cancelSessionOccurrence(occurrence.occurrence_id, {
        reason: reason.trim(),
        notify,
      });
    },
    onSuccess: onCancelled,
    onError: (err: Error) =>
      setError(err.message ?? "Failed to cancel this class date."),
  });

  const when = occurrence
    ? parseAcademyInstant(occurrence.start_at).toLocaleString("en-US", {
        weekday: "long",
        month: "short",
        day: "numeric",
        hour: "numeric",
        minute: "2-digit",
        timeZone,
      })
    : "";

  return (
    <RallyDialog
      open={open}
      onOpenChange={(next) => {
        if (!next) onClose();
      }}
      title="Cancel this date"
      description={
        when
          ? `${when} will not run. Everyone enrolled is credited this date's share of the month automatically, and the coach is not paid for it.`
          : ""
      }
      overline="Class date"
    >
      {error && <DialogError message={error} />}
      <form
        className="space-y-3"
        onSubmit={(event) => {
          event.preventDefault();
          mutation.mutate();
        }}
      >
        <Field label="Reason">
          <input
            value={reason}
            onChange={(event) => setReason(event.target.value)}
            className={inputClass}
            placeholder="Gym flooded"
            maxLength={500}
          />
        </Field>
        <label className="flex items-center gap-2 text-sm text-rally-muted">
          <input
            type="checkbox"
            checked={notify}
            onChange={(event) => setNotify(event.target.checked)}
          />
          Email the families and the coach
        </label>
        <DialogActions>
          <Button variant="secondary" size="sm" type="button" onClick={onClose}>
            Keep the class
          </Button>
          <Button
            variant="primary"
            size="sm"
            type="submit"
            data-testid="confirm-cancel-occurrence"
            disabled={mutation.isPending || reason.trim().length === 0}
          >
            {mutation.isPending ? "Cancelling..." : "Cancel this date"}
          </Button>
        </DialogActions>
      </form>
    </RallyDialog>
  );
}

const ATTENDANCE_CHIP: Record<string, string> = {
  present: "bg-rally-line text-rally-ink",
  late: "bg-rally-line text-rally-ink",
  absent: "bg-rally-line text-rally-muted",
  voided: "bg-rally-line text-rally-subtle line-through",
};

/**
 * Per-student attendance for one class date, with "Void mark" (issue #554).
 *
 * A void is not a delete: the row survives with who voided it and why, and
 * every downstream reader (attendance rate, payroll, absence policy) then
 * treats the student as unmarked. The reason is required because it is the
 * only explanation anyone reading the history later gets, so the confirm
 * button stays disabled until one is typed.
 */
export function OccurrenceAttendanceDialog({
  occurrence,
  timezone,
  studentNameById,
  onClose,
}: {
  occurrence: AdminSessionOccurrenceView | null;
  timezone: string | null;
  studentNameById: Map<string, string>;
  onClose: () => void;
}) {
  const [voidTarget, setVoidTarget] = useState<string | null>(null);
  const [reason, setReason] = useState("");
  const [error, setError] = useState<string | null>(null);
  const open = Boolean(occurrence);
  const { timeZone } = resolveAcademyTimeZone(timezone);
  const occurrenceId = occurrence?.occurrence_id ?? null;

  useEffect(() => {
    if (!open) return;
    setVoidTarget(null);
    setReason("");
    setError(null);
  }, [open, occurrenceId]);

  const attendanceQuery = useQuery({
    queryKey: ["admin", "occurrence-attendance", occurrenceId],
    queryFn: () => listOccurrenceStudentAttendance(occurrenceId as string),
    enabled: open && Boolean(occurrenceId),
  });

  const rows: AdminStudentAttendanceView[] = attendanceQuery.data?.attendance ?? [];

  const mutation = useMutation({
    mutationFn: () => {
      if (!occurrenceId || !voidTarget) throw new Error("No mark selected.");
      return voidOccurrenceStudentAttendance(occurrenceId, voidTarget, reason.trim());
    },
    onSuccess: async () => {
      setVoidTarget(null);
      setReason("");
      await attendanceQuery.refetch();
    },
    onError: (err: Error) => setError(err.message ?? "Failed to void this mark."),
  });

  const when = occurrence
    ? parseAcademyInstant(occurrence.start_at).toLocaleString("en-US", {
        weekday: "long",
        month: "short",
        day: "numeric",
        timeZone,
      })
    : "";

  return (
    <RallyDialog
      open={open}
      onOpenChange={(next) => {
        if (!next) onClose();
      }}
      title="Attendance"
      description={
        when
          ? `${when}. Voiding a mark leaves it on the record but stops it counting towards attendance, payroll and absence policy.`
          : ""
      }
      overline="Class date"
    >
      {error && <DialogError message={error} />}
      {attendanceQuery.isLoading ? (
        <p className="text-sm text-rally-subtle">Loading marks...</p>
      ) : rows.length === 0 ? (
        <p className="text-sm text-rally-subtle">
          No attendance was recorded for this date.
        </p>
      ) : (
        <ul className="space-y-2" data-testid="occurrence-attendance-list">
          {rows.map((row) => (
            <li
              key={row.attendance_id}
              className="flex items-center justify-between gap-3 border-b border-rally-line/60 pb-2"
            >
              <div className="min-w-0">
                <p className="truncate text-sm font-medium text-rally-ink">
                  {studentNameById.get(row.student_id) ?? row.student_id}
                </p>
                <span
                  className={`inline-flex items-center rounded-full px-2 py-0.5 text-xs font-medium capitalize ${
                    ATTENDANCE_CHIP[row.status] ?? "bg-rally-line text-rally-muted"
                  }`}
                  data-testid={`attendance-status-${row.student_id}`}
                >
                  {row.status}
                </span>
                {row.status === "voided" && row.correction_reason && (
                  <p className="mt-1 text-xs text-rally-subtle">
                    Voided: {row.correction_reason}
                  </p>
                )}
              </div>
              {row.status !== "voided" && (
                <Button
                  variant="secondary"
                  size="sm"
                  type="button"
                  data-testid={`void-attendance-${row.student_id}`}
                  onClick={() => {
                    setVoidTarget(row.student_id);
                    setReason("");
                    setError(null);
                  }}
                >
                  Void mark
                </Button>
              )}
            </li>
          ))}
        </ul>
      )}

      {voidTarget && (
        <form
          className="mt-4 space-y-3"
          onSubmit={(event) => {
            event.preventDefault();
            mutation.mutate();
          }}
        >
          <Field
            label={`Why is ${studentNameById.get(voidTarget) ?? voidTarget}'s mark being voided?`}
          >
            <input
              value={reason}
              onChange={(event) => setReason(event.target.value)}
              className={inputClass}
              placeholder="Marked on the wrong class"
              maxLength={500}
              data-testid="void-attendance-reason"
            />
          </Field>
          <DialogActions>
            <Button
              variant="secondary"
              size="sm"
              type="button"
              onClick={() => setVoidTarget(null)}
            >
              Keep the mark
            </Button>
            <Button
              variant="primary"
              size="sm"
              type="submit"
              data-testid="confirm-void-attendance"
              disabled={mutation.isPending || reason.trim().length === 0}
            >
              {mutation.isPending ? "Voiding..." : "Void mark"}
            </Button>
          </DialogActions>
        </form>
      )}
    </RallyDialog>
  );
}

export function OccurrenceReplacementDialog({
  sessionId,
  open,
  occurrence,
  onClose,
  onSaved,
}: {
  sessionId: string;
  open: boolean;
  occurrence: AdminSessionOccurrenceView | null;
  onClose: () => void;
  onSaved: () => void;
}) {
  const isEditing = Boolean(occurrence);
  const dialogOpen = open || isEditing;
  const [dateValue, setDateValue] = useState("");
  const [coachId, setCoachId] = useState("");
  const [reason, setReason] = useState("");
  const [error, setError] = useState<string | null>(null);
  const coachesQuery = useQuery({
    queryKey: queryKeys.admin.users("coach"),
    queryFn: () => listAdminUsers("coach"),
    enabled: dialogOpen,
  });
  const coaches = coachesQuery.data?.users ?? [];

  useEffect(() => {
    if (!dialogOpen) return;
    setDateValue(occurrence ? toDateInputValue(occurrence.start_at) : "");
    setCoachId(occurrence?.actual_coach_id ?? "");
    setReason("");
    setError(null);
  }, [dialogOpen, occurrence]);

  const mutation = useMutation({
    mutationFn: () => {
      const trimmedReason = reason.trim() || null;
      if (occurrence) {
        return updateSessionOccurrenceReplacement(occurrence.occurrence_id, {
          replacement_coach_id: coachId || null,
          reason: trimmedReason,
        });
      }
      return addSessionReplacement(sessionId, {
        date: dateValue,
        replacement_coach_id: coachId,
        reason: trimmedReason,
      });
    },
    onSuccess: onSaved,
    onError: (err: Error) =>
      setError(err.message ?? "Failed to update replacement coach."),
  });

  const canSave = isEditing
    ? Boolean(occurrence?.actual_coach_id || coachId)
    : Boolean(dateValue && coachId);

  return (
    <RallyDialog
      open={dialogOpen}
      onOpenChange={(open) => {
        if (!open) onClose();
      }}
      title={isEditing ? "Change replacement" : "Add replacement"}
      description="Set the replacement coach for a normal class date."
      overline="Replacement"
    >
      {error && <DialogError message={error} />}
      <form
        className="space-y-3"
        onSubmit={(event) => {
          event.preventDefault();
          mutation.mutate();
        }}
      >
        <Field label="Date">
          <input
            type="date"
            value={dateValue}
            onChange={(event) => setDateValue(event.target.value)}
            className={inputClass}
            min={todayDateInput()}
            max={dateInputValueFromOffset(60)}
            disabled={isEditing}
          />
        </Field>
        <Field label="Replacement coach">
          {coaches.length > 0 ? (
            <CoachSelect
              coaches={coaches}
              value={coachId}
              onChange={setCoachId}
              allowEmpty={isEditing}
              emptyLabel={isEditing ? "No replacement" : "Select coach"}
            />
          ) : (
            <input
              value={coachId}
              onChange={(event) => setCoachId(event.target.value)}
              className={inputClass}
              placeholder={
                coachesQuery.isLoading
                  ? "Loading coaches..."
                  : "Coach reference"
              }
            />
          )}
        </Field>
        <Field label="Reason">
          <input
            value={reason}
            onChange={(event) => setReason(event.target.value)}
            className={inputClass}
            placeholder="Optional"
          />
        </Field>
        <DialogActions>
          <Button variant="secondary" size="sm" type="button" onClick={onClose}>
            Cancel
          </Button>
          <Button
            variant="primary"
            size="sm"
            type="submit"
            disabled={mutation.isPending || !canSave}
          >
            {mutation.isPending ? "Saving..." : "Save"}
          </Button>
        </DialogActions>
      </form>
    </RallyDialog>
  );
}

/**
 * Per-session assistant coaches. Candidates are every academy user holding
 * `coach` or `assistant_coach` (two role-filtered directory reads, merged),
 * minus the lead coach — a coach cannot assist their own session. Saves
 * through the dedicated PUT so the edit dialog's PATCH never has to carry the
 * list (there `undefined` means unchanged and `[]` clears, which is easy to
 * get wrong from a form).
 */
export function SessionAssistantsDialog({
  open,
  session,
  onOpenChange,
  onSaved,
}: {
  open: boolean;
  session: AdminSessionView | null;
  onOpenChange: (open: boolean) => void;
  onSaved: (session: AdminSessionView) => void;
}) {
  const [selected, setSelected] = useState<string[]>([]);
  const [reason, setReason] = useState("");
  const [error, setError] = useState<string | null>(null);
  const coachesQuery = useQuery({
    queryKey: queryKeys.admin.users("coach"),
    queryFn: () => listAdminUsers("coach"),
    enabled: open,
  });
  const assistantsQuery = useQuery({
    queryKey: queryKeys.admin.users("assistant_coach"),
    queryFn: () => listAdminUsers("assistant_coach"),
    enabled: open,
  });
  const loading = coachesQuery.isLoading || assistantsQuery.isLoading;

  useEffect(() => {
    if (!open || !session) return;
    setSelected([...(session.assistant_coach_ids ?? [])]);
    setReason("");
    setError(null);
  }, [open, session]);

  const candidates = useMemo(() => {
    const byId = new Map<string, AdminUserView>();
    for (const user of [
      ...(coachesQuery.data?.users ?? []),
      ...(assistantsQuery.data?.users ?? []),
    ]) {
      if (user.user_id === session?.coach_id) continue;
      if (!byId.has(user.user_id)) byId.set(user.user_id, user);
    }
    return [...byId.values()].sort((a, b) =>
      (a.display_name || a.email).localeCompare(b.display_name || b.email),
    );
  }, [coachesQuery.data, assistantsQuery.data, session?.coach_id]);

  // Assistants already on the session whose membership no longer appears in
  // the directory (role removed, account disabled) stay visible so an admin
  // can un-tick them instead of silently dropping them on save.
  const orphaned = useMemo(() => {
    const known = new Set(candidates.map((user) => user.user_id));
    const ids = session?.assistant_coach_ids ?? [];
    const names = session?.assistant_coach_names ?? [];
    return ids
      .map((assistantId, index) => ({ user_id: assistantId, label: names[index] ?? assistantId }))
      .filter((entry) => !known.has(entry.user_id));
  }, [candidates, session?.assistant_coach_ids, session?.assistant_coach_names]);

  const mutation = useMutation({
    mutationFn: () =>
      setSessionAssistants(session!.session_id, selected, reason.trim() || null),
    onSuccess: (savedSession) => {
      setError(null);
      onSaved(savedSession);
    },
    onError: (err: Error) =>
      setError(err.message || "Failed to update assistant coaches."),
  });

  const toggle = (userId: string) =>
    setSelected((prev) =>
      prev.includes(userId) ? prev.filter((id) => id !== userId) : [...prev, userId],
    );

  const optionClass =
    "flex items-start gap-3 rounded-md border border-rally-line px-3 py-2 text-sm";

  return (
    <RallyDialog
      open={open}
      onOpenChange={(nextOpen) => {
        if (!nextOpen) setError(null);
        onOpenChange(nextOpen);
      }}
      title="Edit assistants"
      description="Assistants see this session in their coach app and can mark attendance, update skills and add notes. They are never paid by payroll."
      overline="Coaching staff"
    >
      {error && <DialogError message={error} />}
      <form
        className="space-y-3"
        data-testid="session-assistants-form"
        onSubmit={(event) => {
          event.preventDefault();
          mutation.mutate();
        }}
      >
        <Field label="Assistant coaches">
          {loading ? (
            <p className="text-sm text-rally-subtle">Loading coaches...</p>
          ) : candidates.length === 0 && orphaned.length === 0 ? (
            <p className="text-sm text-rally-subtle" data-testid="assistant-options-empty">
              No coaches or assistant coaches to choose from. Grant the Assistant
              coach role from a user&apos;s page first.
            </p>
          ) : (
            <div className="max-h-72 space-y-2 overflow-y-auto">
              {candidates.map((user) => (
                <label key={user.user_id} className={optionClass}>
                  <input
                    type="checkbox"
                    className="mt-0.5"
                    checked={selected.includes(user.user_id)}
                    onChange={() => toggle(user.user_id)}
                    data-testid={`assistant-option-${user.user_id}`}
                  />
                  <span className="min-w-0 flex-1">
                    <span className="block font-medium text-rally-ink">
                      {user.display_name || user.email}
                    </span>
                    <span className="block truncate font-mono text-[11px] text-rally-muted">
                      {user.email} · {roleLabel(user.role)}
                    </span>
                  </span>
                </label>
              ))}
              {orphaned.map((entry) => (
                <label key={entry.user_id} className={optionClass}>
                  <input
                    type="checkbox"
                    className="mt-0.5"
                    checked={selected.includes(entry.user_id)}
                    onChange={() => toggle(entry.user_id)}
                    data-testid={`assistant-option-${entry.user_id}`}
                  />
                  <span className="min-w-0 flex-1">
                    <span className="block font-medium text-rally-ink">{entry.label}</span>
                    <span className="block text-[11px] text-amber-700">
                      No longer holds a coaching role — un-tick to remove.
                    </span>
                  </span>
                </label>
              ))}
            </div>
          )}
        </Field>
        <Field label="Reason">
          <input
            value={reason}
            onChange={(event) => setReason(event.target.value)}
            className={inputClass}
            placeholder="Optional"
          />
        </Field>
        <DialogActions>
          <Button
            variant="secondary"
            size="sm"
            type="button"
            onClick={() => onOpenChange(false)}
          >
            Cancel
          </Button>
          <Button
            variant="primary"
            size="sm"
            type="submit"
            disabled={mutation.isPending || !session}
          >
            {mutation.isPending ? "Saving..." : "Save"}
          </Button>
        </DialogActions>
      </form>
    </RallyDialog>
  );
}

export function SessionEditDialog({
  open,
  session,
  onOpenChange,
  onSaved,
}: {
  open: boolean;
  session: AdminSessionView | null;
  onOpenChange: (open: boolean) => void;
  onSaved: (session: AdminSessionView) => void;
}) {
  const [form, setForm] = useState<EditSessionRequest>({});
  const [error, setError] = useState<string | null>(null);
  const coachesQuery = useQuery({
    queryKey: queryKeys.admin.users("coach"),
    queryFn: () => listAdminUsers("coach"),
    enabled: open,
  });
  const coaches = coachesQuery.data?.users ?? [];
  useEffect(() => {
    if (!session || !open) return;
    setForm(buildEditSessionForm(session));
  }, [open, session]);

  const recurring = session ? hasRecurringSchedule(session) : false;
  const selectedDays = form.days_of_week ?? [];

  const mutation = useMutation({
    mutationFn: (payload: EditSessionRequest) =>
      updateAdminSession(session!.session_id, payload),
    onSuccess: (savedSession) => {
      setError(null);
      onSaved(savedSession);
    },
    onError: (err: Error) =>
      setError(err.message ?? "Failed to update session."),
  });

  return (
    <RallyDialog
      open={open}
      onOpenChange={(nextOpen) => {
        if (!nextOpen) {
          setError(null);
          setForm({});
        }
        onOpenChange(nextOpen);
      }}
      title="Edit session"
      description="Update recurring schedule, capacity, and coach assignment."
      overline="Session"
    >
      {error && <DialogError message={error} />}
      <form
        className="space-y-3"
        onSubmit={(event) => {
          event.preventDefault();
          mutation.mutate(form);
        }}
      >
        <Field label="Coach">
          {coaches.length > 0 ? (
            <CoachSelect
              coaches={coaches}
              value={form.coach_id ?? ""}
              onChange={(coachId) =>
                setForm((f) => ({ ...f, coach_id: coachId }))
              }
            />
          ) : (
            <input
              value={form.coach_id ?? ""}
              onChange={(event) =>
                setForm((f) => ({ ...f, coach_id: event.target.value }))
              }
              className={inputClass}
              placeholder={
                coachesQuery.isLoading
                  ? "Loading coaches..."
                  : "Coach reference"
              }
            />
          )}
        </Field>
        <Field label="Name">
          <input
            value={form.title ?? ""}
            onChange={(event) =>
              setForm((f) => ({ ...f, title: event.target.value }))
            }
            className={inputClass}
          />
        </Field>
        <Field label="Location">
          <input
            value={form.location ?? ""}
            onChange={(event) =>
              setForm((f) => ({ ...f, location: event.target.value }))
            }
            className={inputClass}
          />
        </Field>
        <div className="grid grid-cols-2 gap-3">
          <Field label={recurring ? "Day of week" : "Date"}>
            {recurring ? (
              selectedDays.length <= 1 ? (
                <DaySelect
                  value={selectedDays[0] ?? "Wed"}
                  onChange={(day) =>
                    setForm((f) => ({ ...f, days_of_week: [day] }))
                  }
                />
              ) : (
                <input
                  value={selectedDays.join(", ")}
                  readOnly
                  className={inputClass}
                />
              )
            ) : (
              <input
                value={session ? sessionDateLabel(session) : ""}
                readOnly
                className={inputClass}
              />
            )}
          </Field>
          <Field label="Start time">
            <input
              type="time"
              value={form.start_time ?? ""}
              onChange={(event) =>
                setForm((f) => ({ ...f, start_time: event.target.value }))
              }
              className={inputClass}
              disabled={!recurring}
            />
          </Field>
        </div>
        <div className="grid grid-cols-2 gap-3">
          <Field label="End time">
            <input
              type="time"
              value={form.end_time ?? ""}
              onChange={(event) =>
                setForm((f) => ({ ...f, end_time: event.target.value }))
              }
              className={inputClass}
              disabled={!recurring}
            />
          </Field>
          <Field label="Capacity">
            <input
              type="number"
              min={1}
              value={form.capacity ?? 1}
              onChange={(event) =>
                setForm((f) => ({
                  ...f,
                  capacity: parseInt(event.target.value, 10) || 1,
                }))
              }
              className={inputClass}
            />
          </Field>
        </div>
        <Field label="Monthly fee">
          <input
            type="number"
            min={0}
            step="0.01"
            value={centsToDollarsInput(form.amount_cents)}
            onChange={(event) =>
              setForm((f) => ({
                ...f,
                amount_cents: dollarsInputToCents(event.target.value),
              }))
            }
            className={inputClass}
          />
          <p className="text-xs text-amber-700">
            Percent-paid coaches require a session price for payroll. Leave
            blank only when pricing is not configured; enter 0 for an explicitly
            free session.
          </p>
        </Field>
        <CommunicationPackSection form={form} setForm={setForm} />
        <Field label="Reason">
          <input
            value={form.reason ?? ""}
            onChange={(event) =>
              setForm((f) => ({ ...f, reason: event.target.value }))
            }
            className={inputClass}
            placeholder="Optional"
          />
        </Field>
        <DialogActions>
          <Button
            variant="secondary"
            size="sm"
            type="button"
            onClick={() => onOpenChange(false)}
          >
            Cancel
          </Button>
          <Button
            variant="primary"
            size="sm"
            type="submit"
            disabled={mutation.isPending}
          >
            {mutation.isPending ? "Saving..." : "Save"}
          </Button>
        </DialogActions>
      </form>
    </RallyDialog>
  );
}

/**
 * Optional per-session onboarding facts (#613). Collapsed by default: it is a
 * long, rarely-edited block and the dialog's common job is a time or capacity
 * change. Plain controlled state and a plain button rather than a new ds
 * primitive — the design system has no accordion, and one dialog is not a
 * reason to add one.
 */
function CommunicationPackSection({
  form,
  setForm,
}: {
  form: EditSessionRequest;
  setForm: React.Dispatch<React.SetStateAction<EditSessionRequest>>;
}) {
  const [open, setOpen] = useState(false);
  const link = form.whatsapp_group_link ?? "";
  const linkLooksWrong = !looksLikeWebUrl(link);
  const linkIsNotAGroupInvite =
    link.trim() !== "" &&
    !linkLooksWrong &&
    !looksLikeWhatsAppGroupInvite(link);

  const setText = (key: keyof EditSessionRequest) => (value: string) =>
    // Empty string must become null, or clearing a box would leave the old
    // value in place (the API only clears on an explicit null).
    setForm((f) => ({ ...f, [key]: blankToNull(value) }));

  return (
    <div className="rounded-md border border-rally-line">
      <button
        type="button"
        onClick={() => setOpen((value) => !value)}
        aria-expanded={open}
        className="flex w-full items-center justify-between px-3 py-2 text-left text-sm font-medium text-rally-ink"
      >
        <span>Communication pack (optional)</span>
        <span aria-hidden className="text-rally-muted">
          {open ? "−" : "+"}
        </span>
      </button>
      {open ? (
        <div className="space-y-3 border-t border-rally-line px-3 py-3">
          <p className="text-xs text-rally-muted">
            These details are emailed to a family when they join this session.
            Leave anything blank to keep it out of the email.
          </p>
          <Field label="WhatsApp group link">
            <input
              type="url"
              inputMode="url"
              value={link}
              onChange={(event) =>
                setText("whatsapp_group_link")(event.target.value)
              }
              className={inputClass}
              placeholder="https://chat.whatsapp.com/..."
            />
            <p className="text-xs text-rally-muted">
              In WhatsApp open the group, then Group info › Invite link › Copy
              link. It starts with https://chat.whatsapp.com/ and goes into the
              welcome email and every daily digest for this class.
            </p>
            {linkLooksWrong ? (
              <p className="text-xs text-amber-700">
                Paste the full invite link, starting with https://
              </p>
            ) : null}
            {linkIsNotAGroupInvite ? (
              <p className="text-xs text-amber-700">
                This does not look like a WhatsApp group invite
                (chat.whatsapp.com/…). A wa.me link opens a personal chat, not
                the class group.
              </p>
            ) : null}
          </Field>
          <Field label="Venue address">
            <textarea
              rows={2}
              value={form.venue_address ?? ""}
              onChange={(event) => setText("venue_address")(event.target.value)}
              className={inputClass}
            />
          </Field>
          <Field label="Parking notes">
            <textarea
              rows={2}
              value={form.parking_notes ?? ""}
              onChange={(event) => setText("parking_notes")(event.target.value)}
              className={inputClass}
            />
          </Field>
          <Field label="What to bring">
            <textarea
              rows={2}
              value={form.what_to_bring ?? ""}
              onChange={(event) => setText("what_to_bring")(event.target.value)}
              className={inputClass}
            />
          </Field>
          <Field label="Arrive N minutes before class">
            <input
              type="number"
              min={0}
              max={120}
              value={form.arrival_minutes_before ?? ""}
              onChange={(event) =>
                setForm((f) => ({
                  ...f,
                  arrival_minutes_before:
                    event.target.value.trim() === ""
                      ? null
                      : Math.max(
                          0,
                          Math.min(120, parseInt(event.target.value, 10) || 0),
                        ),
                }))
              }
              className={inputClass}
            />
          </Field>
          <Field label="Coach contact policy">
            <textarea
              rows={2}
              value={form.coach_contact_policy ?? ""}
              onChange={(event) =>
                setText("coach_contact_policy")(event.target.value)
              }
              className={inputClass}
            />
          </Field>
          <Field label="Absence & make-up policy">
            <textarea
              rows={3}
              value={form.absence_policy ?? ""}
              onChange={(event) =>
                setText("absence_policy")(event.target.value)
              }
              className={inputClass}
            />
          </Field>
        </div>
      ) : null}
    </div>
  );
}
