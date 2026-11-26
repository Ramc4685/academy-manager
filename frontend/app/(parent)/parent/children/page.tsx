"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { ChildWaiverStatus } from "@/components/parent/child-waiver-status";
import { Button } from "@/components/ds/button";
import { Modal } from "@/components/ds/modal";
import { Skeleton } from "@/components/ds/skeleton";
import { FormField, fieldDescribedBy } from "@/components/ds/form-field";
import { Chip } from "@/components/ds/chip";
import { EmptyState } from "@/components/ds/empty-state";
import { AbsenceConfirmDialog } from "@/components/parent/absence-confirm-dialog";
import {
  absenceReportedToast,
  canUndoAbsence,
  invalidateAbsenceReaders,
  useWithdrawAbsence,
} from "@/components/parent/absence-undo";
import { useToast } from "@/components/ds/toast";
import { PauseEnrollmentForm } from "@/components/parent/pause-enrollment-form";
import { EnrollmentActions } from "@/components/parent/enrollment-actions";
import { queryKeys } from "@/lib/query/keys";
import {
  getCancellationPreview,
  getChildSchedule,
  getParentAcademy,
  listParentAttendance,
  listParentChildren,
  listParentEnrollments,
  selfCancelEnrollment,
  submitAbsenceNotice,
  type ParentAttendanceRecord,
  type ParentChild,
  type ParentEnrollment,
  type ParentScheduleEntry,
} from "@/lib/api/parent";
import {
  formatAcademyDate,
  formatAcademyDay,
  formatAcademyTimeRange,
  parseAcademyInstant,
} from "@/lib/format/academy-time";
import { nameGradient } from "@/lib/avatar-gradient";
import {
  cancellationResultTitle,
  cancellationSummaryCopy,
  pendingCancellationLabel,
} from "@/lib/format/cancellation-copy";
import {
  departureLabel,
  departureReasonNote,
  isDepartedEnrollment,
} from "@/lib/format/departure-copy";
import {
  holdReturnLabel,
  holdScheduleNote,
  isHeldEnrollment,
  partitionByHold,
} from "@/lib/format/hold-copy";
import { lifecycleLabel } from "@/lib/format/lifecycle-copy";
import { reEnrollHref } from "@/lib/parent/re-enroll";
import {
  ALREADY_REPORTED_LABEL,
  PRESENT_INCLUDING_LATE,
  noClassReason,
  presentIncludingLate,
  scheduleSourceLabel,
} from "@/lib/parent/schedule-events";
import { OneTimeClassChip } from "@/components/parent/one-time-class";
import { ArrivalCheckin } from "@/components/parent/arrival-checkin";
import { dropoffRefetchInterval, parentArrivalView } from "@/lib/dropoff/checkin";
import { AbsenceMakeupStatus } from "@/components/parent/absence-makeup-status";
import {
  AddChildLink,
  OpenRegistrationsCard,
  useParentRegistrations,
} from "@/components/parent/open-registrations";

// Avatar gradients are shared with the kid-first Home cards so the same child
// wears the same colour on both screens (lib/avatar-gradient.ts).

function money(cents: number, currency = "USD"): string {
  return new Intl.NumberFormat("en-US", { style: "currency", currency }).format(cents / 100);
}

export default function ParentChildrenPage() {
  const [now, setNow] = useState(() => Date.now());
  useEffect(() => {
    const timer = window.setInterval(() => setNow(Date.now()), 60_000);
    return () => window.clearInterval(timer);
  }, []);
  const { data, isLoading, isError } = useQuery({
    queryKey: ["parent", "children"],
    queryFn: listParentChildren,
  });
  const { data: attendanceData } = useQuery({
    queryKey: ["parent", "attendance"],
    queryFn: listParentAttendance,
  });
  const { data: academy } = useQuery({
    queryKey: ["parent", "academy"],
    queryFn: getParentAcademy,
  });
  const { data: enrollmentsData } = useQuery({
    queryKey: ["parent", "enrollments"],
    queryFn: listParentEnrollments,
  });

  const registrationsQuery = useParentRegistrations();
  const registrations = registrationsQuery.data?.registrations ?? [];
  const children = data?.children ?? [];
  const allAttendance = attendanceData?.records ?? [];
  const allEnrollments = enrollmentsData?.enrollments ?? [];
  const academyTimezone = academy?.timezone ?? null;
  // Settings overhaul Phase 1 Lane C: hide (not just disable) an action the
  // academy has switched off. Undefined (still loading) defaults true.
  const selfService = academy?.self_service;
  const canReportAbsence = selfService?.can_report_absence ?? true;
  const canRequestPause = selfService?.can_request_pause ?? true;
  const canRequestCancel = selfService?.can_request_cancel ?? true;

  return (
    <section data-testid="parent-children">
      <div className="mb-4 animate-fade-in-up">
        <h1 className="font-display text-2xl font-bold tracking-tight text-rally-ink">My children</h1>
        <p className="text-sm mt-0.5 text-rally-muted">Sessions, attendance &amp; progress</p>
        <AddChildLink className="mt-3" />
      </div>

      <div className="mb-4 empty:hidden">
        <OpenRegistrationsCard rows={registrations} />
      </div>

      {isError ? (
        <p className="text-sm text-status-red-600">Could not load children.</p>
      ) : isLoading ? (
        <div className="space-y-4">
          {[1, 2].map((i) => (
            <div key={i} className="rounded-2xl overflow-hidden border border-rally-line bg-white">
              <div className="h-24 shimmer" />
              <div className="p-4 space-y-2">
                <Skeleton variant="line" width="8rem" />
                <Skeleton variant="line" width="12rem" />
              </div>
            </div>
          ))}
        </div>
      ) : children.length === 0 ? (
        registrations.length > 0 ? null : (
          <div className="rounded-2xl border border-rally-line bg-white p-8 animate-fade-in-up">
            <EmptyState title="No children registered yet." />
          </div>
        )
      ) : (
        <div className="space-y-4 stagger-children">
          {children.map((child) => (
            <ChildCard
              key={child.student_id}
              child={child}
              now={now}
              attendance={allAttendance.filter((r) => r.student_id === child.student_id)}
              enrollments={allEnrollments.filter((e) => e.student_id === child.student_id)}
              academyTimezone={academyTimezone}
              canReportAbsence={canReportAbsence}
              canRequestPause={canRequestPause}
              canRequestCancel={canRequestCancel}
            />
          ))}
        </div>
      )}
    </section>
  );
}

function ChildCard({
  child,
  now,
  attendance,
  enrollments,
  academyTimezone,
  canReportAbsence,
  canRequestPause,
  canRequestCancel,
}: {
  child: ParentChild;
  now: number;
  attendance: ParentAttendanceRecord[];
  enrollments: ParentEnrollment[];
  academyTimezone: string | null;
  canReportAbsence: boolean;
  canRequestPause: boolean;
  canRequestCancel: boolean;
}) {
  const scheduleQuery = useQuery({
    queryKey: ["parent", "child-schedule", child.student_id],
    queryFn: () => getChildSchedule(child.student_id),
    // Drop-off: refetch when a window opens and while it is open, so the
    // button appears and "Waiting for staff" turns into "Checked in".
    refetchInterval: (query) =>
      dropoffRefetchInterval(
        (query.state.data?.entries ?? []).map((e) => ({
          opensAt: e.checkin?.window_opens_at,
          closesAt: e.checkin?.window_closes_at,
          done: e.checkin?.state === "confirmed" || e.status === "cancelled",
        })),
      ),
  });

  const sessions = scheduleQuery.data?.entries ?? [];
  const nextOccurrenceId = sessions.find(
    (session) => session.status !== "cancelled" && parseAcademyInstant(session.start_at).getTime() >= now,
  )?.occurrence_id;
  const gradient = nameGradient(child.full_name);
  const presentCount = presentIncludingLate(attendance);
  const absentCount = attendance.filter((r) => r.status === "absent").length;
  // #740: a held enrollment keeps its seat but produces no sessions. Dropping
  // it here is what made the class vanish from this card with no explanation.
  const {
    active: activeEnrollments,
    held: heldEnrollments,
    other: otherEnrollments,
  } = partitionByHold(enrollments);
  const holdNote = holdScheduleNote(heldEnrollments);
  // #773: `other` is the paused row this card used to drop on the floor. A
  // paused class is still the family's class; it just is not running yet.
  const listedEnrollments = [...activeEnrollments, ...heldEnrollments, ...otherEnrollments];

  return (
    <article className="rounded-2xl overflow-hidden border border-rally-line bg-white animate-fade-in-up transition-all duration-200 hover:shadow-lg">
      {/* Gradient header */}
      <div className="px-4 py-4 flex items-center gap-3.5" style={{ background: gradient }}>
        <div className="h-12 w-12 rounded-xl flex items-center justify-center text-lg font-bold text-white shrink-0 shadow-lg bg-white/20 backdrop-blur-sm">
          {child.full_name[0]}
        </div>
        <div className="flex-1 min-w-0">
          <h2 className="font-bold text-white text-[15px] tracking-tight truncate">{child.full_name}</h2>
          {/* Issue #773: the derived lifecycle and its date, not the dead
              students.status field this card used to print. */}
          {lifecycleLabel(child.lifecycle, child.lifecycle_as_of) && (
            <span
              data-testid={`child-lifecycle-${child.student_id}`}
              className="inline-block mt-1 text-xs font-semibold px-2 py-0.5 rounded-full bg-white/20 text-white"
            >
              {lifecycleLabel(child.lifecycle, child.lifecycle_as_of)}
            </span>
          )}
        </div>
        <div className="flex gap-3 shrink-0 text-center">
          <div>
            <p className="font-bold text-white text-base leading-none">{presentCount}</p>
            <p className="text-white/60 text-[10px] mt-0.5 max-w-[4.5rem] leading-tight">{PRESENT_INCLUDING_LATE}</p>
          </div>
          <div className="w-px self-stretch bg-white/20" />
          <div>
            <p className="font-bold text-white text-base leading-none">{absentCount}</p>
            <p className="text-white/60 text-[10px] mt-0.5">Absent</p>
          </div>
        </div>
      </div>

      <div className="px-4 py-2 border-b border-rally-line empty:hidden">
        <ChildWaiverStatus studentId={child.student_id} />
      </div>

      {/* Sessions */}
      <div className="px-4 py-3 border-b border-rally-line">
        <p className="text-[10px] font-bold uppercase tracking-widest mb-2.5 text-rally-cobalt-600">
          Upcoming sessions
        </p>
        {scheduleQuery.isPending ? (
          <p role="status" className="text-xs py-1 text-rally-muted">Loading class schedule…</p>
        ) : scheduleQuery.isError && sessions.length === 0 ? (
          <div className="flex flex-wrap items-center gap-2">
            <p role="alert" className="text-xs py-1 text-status-red-800">Could not load the class schedule.</p>
            <Button size="sm" variant="secondary" onClick={() => void scheduleQuery.refetch()}>
              Retry schedule
            </Button>
          </div>
        ) : sessions.length === 0 ? (
          <p className="text-xs py-1 text-rally-subtle">{holdNote ?? "No upcoming sessions."}</p>
        ) : (
          <ul className="space-y-2">
            {sessions.map((s) => (
              <SessionRow
                key={s.occurrence_id}
                studentId={child.student_id}
                childName={child.full_name}
                entry={s}
                isNextClass={s.occurrence_id === nextOccurrenceId}
                academyTimezone={academyTimezone}
                canReportAbsence={canReportAbsence}
              />
            ))}
          </ul>
        )}
        <Link
          href={`/parent/progress?child=${encodeURIComponent(child.student_id)}#coach-notes`}
          className="mt-2 inline-flex min-h-touch items-center text-sm font-semibold text-rally-cobalt-700 underline"
        >
          Coach notes for {child.full_name}
        </Link>
        <Link
          href={`/parent/profile#child-${encodeURIComponent(child.student_id)}`}
          data-testid={`child-edit-details-${child.student_id}`}
          className="mt-1 flex min-h-touch items-center text-sm font-semibold text-rally-cobalt-700 underline"
        >
          Edit emergency contact and medical notes
        </Link>
        {/* S48 (D-24): a second class for this child reuses their record. */}
        <Link
          href={reEnrollHref(child.student_id) as Parameters<typeof Link>[0]["href"]}
          data-testid={`child-add-class-${child.student_id}`}
          className="mt-1 flex min-h-touch items-center text-sm font-semibold text-rally-cobalt-700 underline"
        >
          Add another class for {child.full_name}
        </Link>
      </div>

      {/* Enrollments */}
      {listedEnrollments.length > 0 && (
        <div className="px-4 py-3 border-b border-rally-line">
          <p className="text-[10px] font-bold uppercase tracking-widest mb-2.5 text-rally-cobalt-600">
            Enrollments
          </p>
          <ul className="space-y-2">
            {listedEnrollments.map((e) => (
              <EnrollmentRow
                key={e.enrollment_id}
                enrollment={e}
                academyTimezone={academyTimezone}
                canRequestPause={canRequestPause}
                canRequestCancel={canRequestCancel}
              />
            ))}
          </ul>
        </div>
      )}

      {/* Attendance log */}
      <div className="px-4 py-3">
        <p className="text-[10px] font-bold uppercase tracking-widest mb-2 text-rally-cobalt-600">
          Attendance log
        </p>
        {attendance.length === 0 ? (
          <p className="text-xs py-1 text-rally-subtle">No records yet.</p>
        ) : (
          <ul className="divide-y divide-rally-line">
            {attendance.map((r) => (
              <AttendanceRow key={r.attendance_id} record={r} academyTimezone={academyTimezone} />
            ))}
          </ul>
        )}
      </div>
    </article>
  );
}

function SessionRow({
  studentId,
  childName,
  entry,
  isNextClass,
  academyTimezone,
  canReportAbsence,
}: {
  studentId: string;
  childName: string;
  entry: ParentScheduleEntry;
  isNextClass: boolean;
  academyTimezone: string | null;
  canReportAbsence: boolean;
}) {
  const queryClient = useQueryClient();
  const [submitted, setSubmitted] = useState(false);
  const [confirming, setConfirming] = useState(false);
  const whenStr = formatAcademyTimeRange(entry.start_at, entry.end_at, academyTimezone);
  // #671: a cancelled date is still returned by the child-schedule feed.
  // Showing it as a normal upcoming class contradicts the cancellation email
  // — and reporting an absence for a class that will not run makes no sense.
  const cancelled = entry.status === "cancelled";
  // #1038: an approved make-up / trial sits alongside regular classes.
  const sourceLabel = scheduleSourceLabel(entry.source);
  // A child already dropped off is not absent: no "Report absence" beside it.
  const arrival = parentArrivalView(entry);
  const arrived = arrival === "pending" || arrival === "confirmed";

  const { toast } = useToast();
  const absenceKey = { student_id: studentId, occurrence_id: entry.occurrence_id };
  const withdrawMutation = useWithdrawAbsence(() => setSubmitted(false));
  const absenceMutation = useMutation({
    mutationFn: submitAbsenceNotice,
    onSuccess: () => {
      setSubmitted(true);
      setConfirming(false);
      // S43: the success toast carries Undo (D-12).
      toast(absenceReportedToast(() => withdrawMutation.mutate(absenceKey)));
      // S17: Home and Calendar show the chip too, so refresh every reader.
      invalidateAbsenceReaders(queryClient);
    },
  });

  return (
    <li className="flex flex-col gap-2 rounded-xl p-3 bg-rally-cobalt-50">
      <div className="flex gap-3">
        <div className="h-9 w-9 rounded-lg flex items-center justify-center shrink-0 bg-rally-cobalt-600">
          <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="white" strokeWidth="2.5" strokeLinecap="round" strokeLinejoin="round">
            <rect x="3" y="4" width="18" height="18" rx="2" /><line x1="16" y1="2" x2="16" y2="6" /><line x1="8" y1="2" x2="8" y2="6" /><line x1="3" y1="10" x2="21" y2="10" />
          </svg>
        </div>
        <div className="min-w-0 flex-1">
          {isNextClass && (
            <p className="mb-1 text-xs font-semibold text-rally-cobalt-700">Next class</p>
          )}
          <p
            className={
              cancelled
                ? "text-sm font-semibold truncate text-status-slate-600 line-through"
                : "text-sm font-semibold truncate text-rally-ink"
            }
          >
            {entry.session_title}
          </p>
          <p className="text-xs mt-0.5 text-status-slate-600">{whenStr}</p>
          {sourceLabel && (
            <div className="mt-1">
              <OneTimeClassChip source={entry.source} />
            </div>
          )}
          {cancelled && (
            <p className="text-[11px] mt-0.5 font-semibold text-status-red-800">
              No class — {noClassReason(entry)}
            </p>
          )}
          {(entry.location || entry.coach_name) && (
            <div className="flex flex-wrap gap-1.5 mt-1">
              {entry.location && <span className="text-[11px] text-status-slate-600">{entry.location}</span>}
              {entry.coach_name && (
                <span className="text-[11px] font-semibold px-1.5 py-0.5 rounded bg-rally-cobalt-600/10 text-rally-cobalt-600">
                  {entry.coach_name}
                </span>
              )}
            </div>
          )}
        </div>
      </div>

      <ArrivalCheckin studentId={studentId} childName={childName} entry={entry} />

      {absenceMutation.isError && (
        <p role="alert" className="text-xs text-status-red-800">
          {absenceMutation.error instanceof Error ? absenceMutation.error.message : "Could not report absence."}
        </p>
      )}

      {cancelled || !canReportAbsence || arrived ? null : submitted || entry.absence_reported ? (
        <div>
          {/* Text, not a disabled button: a disabled button is skipped by Tab,
              so keyboard and screen-reader users would never hear it. */}
          <p
            role="status"
            data-testid={`absence-reported-${entry.occurrence_id}`}
            className="text-xs font-semibold text-status-green-800"
          >
            {submitted ? "Absence reported" : ALREADY_REPORTED_LABEL}
          </p>
          {canUndoAbsence(entry.start_at) && (
            <button
              type="button"
              className="min-h-touch text-xs font-semibold text-rally-cobalt-700 underline"
              disabled={withdrawMutation.isPending}
              onClick={() => withdrawMutation.mutate(absenceKey)}
            >
              {withdrawMutation.isPending ? "Undoing…" : "Undo"}
            </button>
          )}
          {withdrawMutation.isError && (
            <p role="alert" className="text-xs text-status-red-800">
              {withdrawMutation.error instanceof Error
                ? withdrawMutation.error.message
                : "Could not undo the absence."}
            </p>
          )}
          {/* A reported date also shows where it stands with makeups; a plain
              "reported" adds nothing to "Already reported". */}
          {!submitted &&
            entry.absence_makeup &&
            !(entry.absence_makeup.state === "reported" && !entry.absence_makeup.reason) && (
            <AbsenceMakeupStatus
              makeup={entry.absence_makeup}
              studentId={studentId}
              occurrenceId={entry.occurrence_id}
              academyTimezone={academyTimezone}
            />
          )}
        </div>
      ) : (
        <Button
          variant="secondary"
          size="sm"
          disabled={absenceMutation.isPending}
          onClick={() => setConfirming(true)}
        >
          {absenceMutation.isPending ? "Reporting…" : "Report absence"}
        </Button>
      )}
      <AbsenceConfirmDialog
        open={confirming}
        onOpenChange={setConfirming}
        childName={childName}
        sessionTitle={entry.session_title}
        when={whenStr}
        pending={absenceMutation.isPending}
        onConfirm={() =>
          absenceMutation.mutate({
            student_id: studentId,
            occurrence_id: entry.occurrence_id,
          })
        }
      />
    </li>
  );
}

function EnrollmentRow({
  enrollment,
  academyTimezone,
  canRequestPause,
  canRequestCancel,
}: {
  enrollment: ParentEnrollment;
  academyTimezone: string | null;
  canRequestPause: boolean;
  canRequestCancel: boolean;
}) {
  const [confirming, setConfirming] = useState(false);
  // #843: pausing moved here from the Payments page — it belongs with the
  // class, next to cancel, not next to autopay setup.
  const [pausing, setPausing] = useState(false);
  const pendingLabel = pendingCancellationLabel(enrollment.pending_cancellation_at, academyTimezone);
  // #740: a held enrollment cannot be self-cancelled (the API allows it only
  // while active), so offering the button here would only produce an error.
  const held = isHeldEnrollment(enrollment);
  // #775: a terminal row carried for history. It is not a seat and not money,
  // so it gets a date and a reason — never a cancel button.
  const departed = isDepartedEnrollment(enrollment);
  const departureNote = departureReasonNote(enrollment.departure_reason);

  return (
    <li className="rounded-xl p-3 bg-rally-paper">
      <div className="flex items-start justify-between gap-3">
        <div className="min-w-0 flex-1">
          {/* The full class name wraps; cut short beside two inline buttons it
              left "Junior Beginners" as a 17 px sliver on a 390 px phone. */}
          <p className="text-sm font-semibold break-words text-rally-ink">{enrollment.session_title}</p>
          <p className="text-xs mt-0.5 text-rally-muted">
            {departed
              ? "Your child has left this class"
              : held
                ? "Your child's place is being kept"
                : pendingLabel
                  ? "Cancellation scheduled"
                  : "Active enrollment"}
          </p>
          {departed && (
            <div className="mt-1" data-testid={`enrollment-departed-${enrollment.enrollment_id}`}>
              <Chip
                variant="expired"
                label={departureLabel(enrollment.left_on, (iso) =>
                  formatAcademyDay(iso, academyTimezone),
                )}
              />
              {departureNote && (
                <p className="text-[11px] mt-1 text-rally-muted">{departureNote}</p>
              )}
            </div>
          )}
          {!departed && held && (
            <div className="mt-1">
              <Chip variant="paused" label={holdReturnLabel(enrollment.hold_return_on)} />
            </div>
          )}
          {!departed && !held && pendingLabel && (
            <div className="mt-1">
              <Chip variant="pending" label={pendingLabel} />
            </div>
          )}
        </div>
        {/* #827: the way back in. A departed row is still history — this is a
            link into onboarding with the child pinned, never an action on the
            dead enrollment, and never a payment control. */}
        {departed && (
          <Link
            href={reEnrollHref(enrollment.student_id) as Parameters<typeof Link>[0]["href"]}
            data-testid={`enrollment-re-enroll-${enrollment.enrollment_id}`}
            className="inline-flex h-[30px] shrink-0 items-center justify-center rounded-lg border border-rally-line bg-white px-3 text-xs font-semibold text-rally-ink transition-colors hover:bg-rally-paper"
          >
            Enroll in a class
          </Link>
        )}
        {!departed && !held && !pendingLabel && (
          <EnrollmentActions
            enrollmentId={enrollment.enrollment_id}
            sessionTitle={enrollment.session_title}
            childName={enrollment.student_name}
            canRequestPause={canRequestPause}
            canRequestCancel={canRequestCancel}
            pausing={pausing}
            onPause={() => setPausing((open) => !open)}
            onCancel={() => setConfirming(true)}
          />
        )}
      </div>
      {pausing && canRequestPause && (
        <PauseEnrollmentForm
          enrollmentId={enrollment.enrollment_id}
          childName={enrollment.student_name}
          sessionTitle={enrollment.session_title}
          onCancel={() => setPausing(false)}
        />
      )}
      {confirming && canRequestCancel && (
        <CancelEnrollmentDialog
          enrollment={enrollment}
          academyTimezone={academyTimezone}
          onClose={() => setConfirming(false)}
        />
      )}
    </li>
  );
}

function CancelEnrollmentDialog({
  enrollment,
  academyTimezone,
  onClose,
}: {
  enrollment: ParentEnrollment;
  academyTimezone: string | null;
  onClose: () => void;
}) {
  const queryClient = useQueryClient();
  const { toast } = useToast();
  const [reason, setReason] = useState("");

  const previewQuery = useQuery({
    queryKey: queryKeys.parent.cancellationPreview(enrollment.enrollment_id),
    queryFn: () => getCancellationPreview(enrollment.enrollment_id),
  });

  const cancelMutation = useMutation({
    mutationFn: () => selfCancelEnrollment(enrollment.enrollment_id, { reason }),
    onSuccess: (res) => {
      void queryClient.invalidateQueries({ queryKey: ["parent", "enrollments"] });
      toast({
        kind: "success",
        title: cancellationResultTitle(res.status),
        description: res.fee_cents > 0 ? `Fee charged: ${money(res.fee_cents)}` : "No fee charged",
      });
      onClose();
    },
  });

  const preview = previewQuery.data;
  const cancelError = cancelMutation.isError
    ? cancelMutation.error instanceof Error
      ? cancelMutation.error.message
      : "Could not cancel enrollment."
    : null;

  return (
    <Modal
      open
      onClose={onClose}
      title={`Cancel ${enrollment.student_name}'s enrollment in ${enrollment.session_title}`}
      dismissable={!cancelMutation.isPending}
    >
      {previewQuery.isError ? (
        <div className="space-y-3">
          <p role="alert" className="text-sm text-status-red-800">
            Could not load cancellation details.
          </p>
          <div className="flex justify-end">
            <Button variant="secondary" size="sm" onClick={onClose}>
              Close
            </Button>
          </div>
        </div>
      ) : previewQuery.isLoading ? (
        <Skeleton variant="line" lines={2} />
      ) : preview ? (
        <div className="space-y-3">
          <div className="text-sm text-rally-ink">
            <p className="font-semibold" data-testid="cancellation-timing-copy">
              {cancellationSummaryCopy(preview, academyTimezone)}
            </p>
            {!preview.allowed && preview.blocked_reason && (
              <p role="alert" className="mt-2 text-xs font-semibold text-status-red-800">
                {preview.blocked_reason}
              </p>
            )}
          </div>

          {preview.allowed ? (
            <>
              <FormField label="Reason" htmlFor="cancel-reason" error={cancelError}>
                <textarea
                  id="cancel-reason"
                  aria-describedby={fieldDescribedBy("cancel-reason", { error: cancelError })}
                  aria-invalid={cancelError ? true : undefined}
                  className="mt-1 w-full rounded-lg border border-rally-line px-3 py-2 text-sm"
                  rows={2}
                  value={reason}
                  onChange={(e) => setReason(e.target.value)}
                  placeholder="Why are you cancelling?"
                />
              </FormField>

              <div className="flex justify-end gap-2">
                <Button variant="secondary" size="sm" onClick={onClose} disabled={cancelMutation.isPending}>
                  Keep enrollment
                </Button>
                <Button
                  variant="danger"
                  size="sm"
                  disabled={!reason.trim() || cancelMutation.isPending}
                  onClick={() => cancelMutation.mutate()}
                >
                  {cancelMutation.isPending ? "Cancelling…" : "Confirm cancellation"}
                </Button>
              </div>
            </>
          ) : (
            <div className="flex justify-end">
              <Button variant="secondary" size="sm" onClick={onClose}>
                Close
              </Button>
            </div>
          )}
        </div>
      ) : null}
    </Modal>
  );
}

function AttendanceRow({
  record,
  academyTimezone,
}: {
  record: ParentAttendanceRecord;
  academyTimezone: string | null;
}) {
  const present = record.status === "present" || record.status === "late";
  return (
    <li className="flex items-center justify-between gap-3 py-2.5 text-xs">
      <div className="min-w-0 flex-1">
        <p className="font-semibold truncate text-rally-ink">{record.session_title}</p>
        {record.coach_name && <p className="mt-0.5 text-rally-muted">{record.coach_name}</p>}
      </div>
      <div className="flex shrink-0 items-center gap-2">
        <span className="text-rally-subtle">{formatAcademyDate(record.marked_at, academyTimezone)}</span>
        <Chip variant={present ? "present" : "absent"} label={record.status} />
      </div>
    </li>
  );
}

