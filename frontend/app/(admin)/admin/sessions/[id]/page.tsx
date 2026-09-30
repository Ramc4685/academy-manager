"use client";

/**
 * Admin session detail — Rally restyle.
 *
 * Preserves: roster table with pause/resume/move/remove, waitlist with
 * skip/remove + "promote next", add-to-roster dialog, transfer dialog,
 * cancel session.
 */

import { useEffect, useMemo, useRef, useState } from "react";
import Link from "next/link";
import { useParams } from "next/navigation";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";

import {
  cancelScheduledDrop,
  getAdminSession,
  listAdminUsers,
  listSessionEnrollments,
  listSessionOccurrences,
  listSessionWaitlist,
  deleteAdminSession,
  promoteWaitlist,
  resumeEnrollment,
  skipWaitlistEntry,
  deleteWaitlistEntry,
  type AdminEnrollmentView,
  type AdminSessionList,
  type AdminSessionOccurrenceView,
  type AdminSessionView,
  type AdminWaitlistEntry,
} from "@/lib/api/admin";
import { getFullPathway, placeStudentInLevel } from "@/lib/api/curriculum";
import { parseAcademyInstant } from "@/lib/format/academy-time";
import { PathwayPlacementUndoWindow } from "@/lib/admin/pathway-placement-undo";
import { queryKeys } from "@/lib/query/keys";

import { Button } from "@/components/ds/button";
import { Card } from "@/components/ds/card";
import { Icon } from "@/components/ds/icons";
import { LaneHeader } from "@/components/ds/lane";
import { TableSkeleton } from "@/components/ds/skeleton";
import { AdminTeachingPlan } from "@/components/teaching/admin-teaching-plan";
import { AnnouncementsPanel } from "@/components/announcements/AnnouncementsPanel";

import { HoldEnrollmentDialog, ReturnFromHoldDialog } from "@/components/admin/enrollment/hold-dialogs";
import { ConfirmActionDialog } from "@/components/admin/confirm-action-dialog";

import { AddToRosterDialog, PauseEnrollmentDialog, RemoveEnrollmentDialog, TransferEnrollmentDialog, WithdrawalCreditDialog } from "./dialogs";
import { formatCurrencyCents, sessionTimeRange } from "./format";
import { RosterMetrics, RosterTable, partitionRoster, seatsHeldCount } from "./RosterPanel";
import {
  CancelOccurrenceDialog,
  OccurrenceAttendanceDialog,
  OccurrenceReplacementDialog,
  ReplacementCoachTable,
  SessionAssistantsDialog,
  SessionEditDialog,
} from "./SessionEditing";
import { WaitlistTable } from "./WaitlistTable";
import { WelcomeEmailTab } from "./WelcomeEmailTab";

const DETAIL_TABS = [
  { id: "roster", label: "Roster" },
  { id: "dates", label: "Class dates" },
  { id: "waitlist", label: "Waitlist" },
  { id: "teaching-plan", label: "Teaching plan" },
  { id: "welcome", label: "Welcome email" },
] as const;
type DetailTab = (typeof DETAIL_TABS)[number]["id"];

const ROSTER_VIEWS = [
  { id: "active", label: "Active" },
  { id: "past", label: "Past" },
] as const;
type RosterView = (typeof ROSTER_VIEWS)[number]["id"];

const CANCEL_FAILED_FALLBACK = "Could not cancel session.";

// #711: a long-running series lists 20+ dates; by default show the 3 most
// recent past dates and the next 3 upcoming, in order.
const CLASS_DATES_WINDOW = 3;

function windowedOccurrences(
  occurrences: AdminSessionOccurrenceView[],
  now: Date,
): AdminSessionOccurrenceView[] {
  const sorted = [...occurrences].sort(
    (a, b) => parseAcademyInstant(a.start_at).getTime() - parseAcademyInstant(b.start_at).getTime(),
  );
  const firstUpcoming = sorted.findIndex(
    (occurrence) => parseAcademyInstant(occurrence.start_at).getTime() >= now.getTime(),
  );
  const splitAt = firstUpcoming === -1 ? sorted.length : firstUpcoming;
  return [
    ...sorted.slice(Math.max(splitAt - CLASS_DATES_WINDOW, 0), splitAt),
    ...sorted.slice(splitAt, splitAt + CLASS_DATES_WINDOW),
  ];
}

function cancelErrorMessage(err: unknown): string {
  const reason = err instanceof Error ? err.message.trim() : "";
  return reason ? `Could not cancel session: ${reason}` : CANCEL_FAILED_FALLBACK;
}

export default function AdminSessionDetailPage() {
  const params = useParams();
  const sessionId = params.id as string;
  const queryClient = useQueryClient();
  const [addOpen, setAddOpen] = useState(false);
  // #827: the departed row an admin chose to put back, pre-filling Add to
  // roster. Cleared when the dialog closes so the next plain Add is blank.
  const [reEnrollTarget, setReEnrollTarget] = useState<AdminEnrollmentView | null>(null);
  const [editOpen, setEditOpen] = useState(false);
  const [pauseTarget, setPauseTarget] = useState<AdminEnrollmentView | null>(null);
  const [removeTarget, setRemoveTarget] = useState<AdminEnrollmentView | null>(null);
  const [transferTarget, setTransferTarget] = useState<AdminEnrollmentView | null>(null);
  const [withdrawalTarget, setWithdrawalTarget] = useState<AdminEnrollmentView | null>(null);
  const [holdTarget, setHoldTarget] = useState<AdminEnrollmentView | null>(null);
  const [returnTarget, setReturnTarget] = useState<AdminEnrollmentView | null>(null);
  const [occurrenceTarget, setOccurrenceTarget] = useState<AdminSessionOccurrenceView | null>(null);
  const [replacementOpen, setReplacementOpen] = useState(false);
  // Issue #671: the date an admin is calling off, or null.
  const [cancelTarget, setCancelTarget] = useState<AdminSessionOccurrenceView | null>(null);
  // Issue #554: the date whose per-student marks an admin is reviewing, or null.
  const [attendanceTarget, setAttendanceTarget] = useState<AdminSessionOccurrenceView | null>(
    null,
  );
  const [assistantsOpen, setAssistantsOpen] = useState(false);
  const [activeTab, setActiveTab] = useState<DetailTab>("roster");
  const [rosterView, setRosterView] = useState<RosterView>("active");
  const [showAllDates, setShowAllDates] = useState(false);
  const [cancelError, setCancelError] = useState<string | null>(null);
  // #838: cancelling the whole session, and dropping someone off the waitlist,
  // now ask a second time and say who is affected.
  const [cancelSessionOpen, setCancelSessionOpen] = useState(false);
  const [waitlistRemoveTarget, setWaitlistRemoveTarget] = useState<AdminWaitlistEntry | null>(null);

  const sessionsQuery = useQuery({
    queryKey: queryKeys.admin.sessionDetail(sessionId),
    queryFn: () => getAdminSession(sessionId),
  });

  const enrollmentsQuery = useQuery({
    queryKey: queryKeys.admin.enrollments(sessionId),
    queryFn: () => listSessionEnrollments(sessionId),
  });

  const occurrencesQuery = useQuery({
    queryKey: queryKeys.admin.sessionOccurrences(sessionId),
    queryFn: () => listSessionOccurrences(sessionId),
  });

  // #521: this page only needs coach names for the replacement-coach table,
  // not the full tenant user directory.
  const usersQuery = useQuery({
    queryKey: queryKeys.admin.users("coach"),
    queryFn: () => listAdminUsers("coach"),
  });

  const waitlistQuery = useQuery({
    queryKey: queryKeys.admin.waitlist(sessionId),
    queryFn: () => listSessionWaitlist(sessionId),
  });

  const cancelSessionMutation = useMutation({
    mutationFn: () => deleteAdminSession(sessionId),
    onMutate: () => {
      setCancelError(null);
    },
    onSuccess: () => {
      window.location.href = "/admin/sessions";
    },
    // #467: a failed cancel used to be silent — no redirect, no message.
    onError: (err: unknown) => {
      // The reason is folded into the message here, not at render time: an API
      // error can carry an EMPTY message (`makeError` builds `new Error("")`
      // for a non-JSON body), and rendering a fixed prefix beside the fallback
      // string produced "Could not cancel session: Could not cancel session."
      setCancelError(cancelErrorMessage(err));
    },
  });

  const promoteMutation = useMutation({
    mutationFn: () => promoteWaitlist(sessionId),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: queryKeys.admin.waitlist(sessionId) });
      void queryClient.invalidateQueries({ queryKey: queryKeys.admin.enrollments(sessionId) });
      void queryClient.invalidateQueries({ queryKey: queryKeys.admin.sessionDetail(sessionId) });
      void queryClient.invalidateQueries({ queryKey: queryKeys.admin.sessions("upcoming") });
    },
  });

  // #509: these were raw `.then()` calls with no `.catch()` — failures became
  // unhandled promise rejections with zero user feedback. As mutations they
  // fall under the global MutationCache onError default (error toast).
  const resumeMutation = useMutation({
    mutationFn: (enrollmentId: string) => resumeEnrollment(enrollmentId),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: queryKeys.admin.enrollments(sessionId) });
      void queryClient.invalidateQueries({ queryKey: queryKeys.admin.waitlist(sessionId) });
      void queryClient.invalidateQueries({ queryKey: queryKeys.admin.sessions("upcoming") });
    },
  });

  // Issue #820: call off a drop scheduled for the end of the period. Same
  // invalidations as a resume — the row's chip and its menu both change.
  const undoScheduledDropMutation = useMutation({
    mutationFn: (enrollmentId: string) => cancelScheduledDrop(enrollmentId),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: queryKeys.admin.enrollments(sessionId) });
    },
  });

  const skipWaitlistMutation = useMutation({
    mutationFn: (entryId: string) => skipWaitlistEntry(entryId),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: queryKeys.admin.waitlist(sessionId) });
    },
  });

  const removeWaitlistMutation = useMutation({
    mutationFn: (entryId: string) => deleteWaitlistEntry(entryId),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: queryKeys.admin.waitlist(sessionId) });
      // X2: withdrawing an offer releases (and re-offers) a held seat.
      void queryClient.invalidateQueries({ queryKey: queryKeys.admin.sessionDetail(sessionId) });
    },
  });

  const session = sessionsQuery.data ?? null;
  const enrollments = useMemo(
    () => enrollmentsQuery.data?.enrollments ?? [],
    [enrollmentsQuery.data?.enrollments],
  );
  const occurrences = occurrencesQuery.data?.occurrences ?? [];
  const canWindowDates = occurrences.length > CLASS_DATES_WINDOW * 2;
  const visibleOccurrences =
    canWindowDates && !showAllDates ? windowedOccurrences(occurrences, new Date()) : occurrences;
  const { active: activeEnrollments, past: pastEnrollments } = partitionRoster(enrollments);
  const rosterRows = rosterView === "active" ? activeEnrollments : pastEnrollments;
  const userNameById = new Map(
    (usersQuery.data?.users ?? []).map((user) => [user.user_id, user.display_name || user.email])
  );
  // The attendance dialog reads ids; the roster already has the names, so no
  // extra request is needed to label them (#554).
  const studentNameById = useMemo(
    () =>
      new Map(
        enrollments.map((enrollment) => [enrollment.student_id, enrollment.full_name]),
      ),
    [enrollments],
  );
  const waitlist = waitlistQuery.data?.waitlist ?? [];
  const waitingCount = waitlist.filter((w) => w.status === "waiting").length;

  const rosterProgramId = useMemo(
    () => enrollments.find((enrollment) => enrollment.pathway_program_id)?.pathway_program_id ?? "",
    [enrollments],
  );

  const pathwayQuery = useQuery({
    queryKey: ["admin", "pathway", rosterProgramId],
    queryFn: () => getFullPathway(rosterProgramId),
    enabled: Boolean(rosterProgramId),
  });

  const pathwayLevels = useMemo(
    () => pathwayQuery.data?.levels.map((entry) => entry.level) ?? [],
    [pathwayQuery.data],
  );

  const placementMutation = useMutation({
    mutationFn: ({
      studentId,
      programId,
      levelId,
    }: {
      studentId: string;
      programId?: string | null;
      levelId: string;
    }) =>
      placeStudentInLevel(studentId, {
        ...(programId ? { program_id: programId } : {}),
        level_id: levelId,
      }),
    onSuccess: (_student, variables) => {
      void queryClient.invalidateQueries({ queryKey: queryKeys.admin.enrollments(sessionId) });
      void queryClient.invalidateQueries({
        queryKey: queryKeys.admin.studentDetail(variables.studentId),
      });
      void queryClient.invalidateQueries({
        queryKey: ["admin", "student-progress", variables.studentId],
      });
    },
  });

  /**
   * #859 remainder: a pathway-level pick from the roster's dropdown used to
   * fire `placementMutation` straight from `onChange` — a misclick silently
   * committed a new placement with no way back. It is now HELD for a few
   * seconds behind `PathwayPlacementUndoWindow` (same DELAYED SAVE shape as
   * `BulkMarkUndoWindow`, #846) while a bar offers Undo; only the window
   * elapsing, another select, or leaving the page actually sends it.
   */
  const [pendingPlacement, setPendingPlacement] = useState<{
    studentId: string;
    studentName: string;
    levelId: string;
    levelName: string;
  } | null>(null);
  const placementUndoRef = useRef<PathwayPlacementUndoWindow | null>(null);
  const placementUndoWindow = (): PathwayPlacementUndoWindow =>
    (placementUndoRef.current ??= new PathwayPlacementUndoWindow());
  // Re-pointed after every render so a change that leaves late still calls
  // the latest mutation instance, matching the coach page's `commitBulkRef`.
  const commitPlacementRef = useRef<
    (change: { studentId: string; programId?: string | null; levelId: string }) => void
  >(() => undefined);
  useEffect(() => {
    commitPlacementRef.current = (change) => placementMutation.mutate(change);
  });
  // Never lose a held placement change: leaving this route unmounts the page
  // and must flush whatever is still waiting, the same rule #846 applies to
  // a held attendance batch.
  useEffect(() => {
    return () => {
      placementUndoRef.current?.flush();
    };
  }, []);

  function handlePathwayLevelChange(enrollment: AdminEnrollmentView, levelId: string): void {
    const level = pathwayLevels.find((l) => l.level_id === levelId);
    setPendingPlacement({
      studentId: enrollment.student_id,
      studentName: enrollment.full_name,
      levelId,
      levelName: level?.name ?? "",
    });
    placementUndoWindow().schedule(
      { studentId: enrollment.student_id, programId: enrollment.pathway_program_id, levelId },
      (change) => {
        commitPlacementRef.current(change);
        setPendingPlacement((current) =>
          current?.studentId === change.studentId && current.levelId === change.levelId
            ? null
            : current,
        );
      },
    );
  }

  function handleUndoPathwayPlacement(): void {
    // cancel() returns null once the change has gone out, so a tap a beat
    // too late is a no-op rather than a half-undone placement.
    placementUndoWindow().cancel();
    setPendingPlacement(null);
  }

  return (
    <section data-testid="admin-session-detail" className="space-y-6">
      {/* Header */}
      <div className="flex flex-wrap items-start justify-between gap-4">
        <div>
          <Link
            href="/admin/sessions"
            className="inline-flex items-center gap-1 font-mono text-[10px] font-bold uppercase tracking-overline text-rally-muted hover:text-rally-ink"
          >
            ← Sessions
          </Link>
          {sessionsQuery.isLoading ? (
            <div className="mt-2 h-8 w-48 animate-pulse rounded bg-rally-line/40" />
          ) : session ? (
            <>
              <h1 className="mt-1 font-display text-[24px] font-semibold tracking-[-0.02em] text-rally-ink">
                {session.title}
              </h1>
              <p className="mt-1 text-sm text-rally-muted">
                {session.location} · {sessionTimeRange(session)}
                {session.coach_name ? ` · Coach ${session.coach_name}` : ""}
                {` · ${formatCurrencyCents(session.amount_cents)}/month`}
              </p>
            </>
          ) : (
            <h1 className="font-display text-2xl font-semibold text-rally-ink">
              Session unavailable
            </h1>
          )}
        </div>
        <div className="flex flex-wrap gap-2">
          {session && (
            <Button variant="secondary" size="sm" onClick={() => setEditOpen(true)}>
              Edit session
            </Button>
          )}
          <Button
            variant="primary"
            size="sm"
            icon={Icon.plus(14, "currentColor")}
            onClick={() => setAddOpen(true)}
          >
            Add to roster
          </Button>
          <Button
            variant="danger"
            size="sm"
            onClick={() => setCancelSessionOpen(true)}
            disabled={cancelSessionMutation.isPending}
          >
            {cancelSessionMutation.isPending ? "Cancelling…" : "Cancel session"}
          </Button>
        </div>
      </div>

      {cancelError && (
        <Card p={16} style={{ borderColor: "#fecaca", background: "#fef2f2" }}>
          <div role="alert" data-testid="admin-session-cancel-error" className="flex items-center justify-between gap-3">
            <p className="text-sm text-red-800">{cancelError}</p>
            <Button variant="secondary" size="sm" onClick={() => setCancelError(null)}>
              Dismiss
            </Button>
          </div>
        </Card>
      )}

      {session && (
        <CoachingStaffStrip session={session} onEditAssistants={() => setAssistantsOpen(true)} />
      )}

      <div className="flex flex-wrap gap-2 border-b border-rally-line">
        {DETAIL_TABS.map((tab) => (
          <button
            key={tab.id}
            type="button"
            data-testid={`session-tab-${tab.id}`}
            onClick={() => setActiveTab(tab.id)}
            className={`min-h-10 border-b-2 px-3 text-sm font-semibold ${
              activeTab === tab.id
                ? "border-rally-cobalt-600 text-rally-ink"
                : "border-transparent text-rally-muted hover:text-rally-ink"
            }`}
          >
            {tab.label}
          </button>
        ))}
      </div>

      {activeTab === "roster" && (
        <Card p={20} className="min-w-0">
          <LaneHeader
            index="01"
            title="Roster"
            action={
              session && (
                <span className="font-mono text-sm font-semibold tabular-nums text-rally-muted">
                  {seatsHeldCount(enrollments)}/{session.capacity}
                </span>
              )
            }
          />
          {session && (
            <RosterMetrics enrollments={enrollments} capacity={session.capacity} />
          )}
          <div
            role="tablist"
            aria-label="Roster view"
            className="mb-4 inline-flex rounded-md border border-rally-line bg-rally-paper p-0.5"
          >
            {ROSTER_VIEWS.map((view) => {
              const selected = rosterView === view.id;
              const count = view.id === "active" ? activeEnrollments.length : pastEnrollments.length;
              return (
                <button
                  key={view.id}
                  type="button"
                  role="tab"
                  aria-selected={selected}
                  data-testid={`roster-tab-${view.id}`}
                  onClick={() => setRosterView(view.id)}
                  className={`inline-flex min-h-9 items-center gap-2 rounded px-3 text-sm font-semibold ${
                    selected
                      ? "bg-white text-rally-ink shadow-sm"
                      : "text-rally-muted hover:text-rally-ink"
                  }`}
                >
                  {view.label}
                  {/* #896: rally-muted is AA on white/paper only — on the
                      rally-line fill it measured 3.86:1. Ink is 14.5:1. */}
                  <span className="rounded-full bg-rally-line px-1.5 font-mono text-[11px] tabular-nums text-rally-ink">
                    {count}
                  </span>
                </button>
              );
            })}
          </div>
          {pendingPlacement && (
            <div
              data-testid="pathway-placement-undo-bar"
              role="status"
              className="mb-3 flex items-center gap-2 rounded-md border p-2"
              style={{ borderColor: "var(--rally-line)", background: "var(--rally-paper)" }}
            >
              <p className="min-w-0 flex-1 text-sm text-rally-ink">
                Moved {pendingPlacement.studentName} to{" "}
                {pendingPlacement.levelName || "the selected level"}
              </p>
              <Button
                variant="secondary"
                size="sm"
                data-testid="pathway-placement-undo"
                onClick={handleUndoPathwayPlacement}
              >
                Undo
              </Button>
            </div>
          )}
          {enrollmentsQuery.isLoading ? (
            <TableSkeleton />
          ) : rosterRows.length === 0 ? (
            rosterView === "active" ? (
              <p className="text-sm text-rally-subtle" data-testid="roster-empty">No active students.</p>
            ) : (
              <p className="text-sm text-rally-subtle" data-testid="roster-past-empty">No past students.</p>
            )
          ) : (
            <RosterTable
              enrollments={rosterRows}
              sessionId={sessionId}
              academyTimezone={session?.timezone ?? null}
              pathwayLevels={pathwayLevels}
              updatingPlacementStudentId={
                placementMutation.isPending ? placementMutation.variables?.studentId : null
              }
              pendingPlacement={pendingPlacement}
              onPathwayLevelChange={handlePathwayLevelChange}
              onDelete={(enrollment) => setRemoveTarget(enrollment)}
              onHold={(enrollment) => setHoldTarget(enrollment)}
              onPause={(enrollment) => setPauseTarget(enrollment)}
              onResume={(id) => resumeMutation.mutate(id)}
              onReturn={(enrollment) => setReturnTarget(enrollment)}
              onTransfer={(enrollment) => setTransferTarget(enrollment)}
              onWithdraw={(enrollment) => setWithdrawalTarget(enrollment)}
              onUndoScheduledDrop={(enrollment) =>
                undoScheduledDropMutation.mutate(enrollment.enrollment_id)
              }
              onReEnroll={(enrollment) => {
                setReEnrollTarget(enrollment);
                setAddOpen(true);
              }}
            />
          )}
        </Card>
      )}

      {activeTab === "roster" && (
        <Card p={20} className="min-w-0">
          <LaneHeader index="02" title="Announcements" />
          <AnnouncementsPanel persona="admin" sessionId={sessionId} />
        </Card>
      )}

      {activeTab === "dates" && (
        // Class dates (#671) — one table. It already carries the replacement
        // column, the replacement action and the cancel action, so a separate
        // "Replacement coaches" card would list every replaced date twice.
        <Card p={20} className="min-w-0" data-testid="session-dates">
          <LaneHeader
            index="01"
            title="Class dates"
            action={
              <Button
                variant="primary"
                size="sm"
                icon={Icon.plus(14, "currentColor")}
                onClick={() => setReplacementOpen(true)}
              >
                Add replacement
              </Button>
            }
          />
          {occurrencesQuery.isLoading ? (
            <TableSkeleton />
          ) : (
            <>
              <ReplacementCoachTable
                occurrences={visibleOccurrences}
                userNameById={userNameById}
                timezone={session?.timezone ?? null}
                onEdit={setOccurrenceTarget}
                onCancel={setCancelTarget}
                onViewAttendance={setAttendanceTarget}
                showStatus
                emptyLabel="No dates scheduled yet."
              />
              {canWindowDates && (
                <div className="pt-3">
                  <Button
                    variant="secondary"
                    size="sm"
                    data-testid="class-dates-show-all"
                    aria-expanded={showAllDates}
                    onClick={() => setShowAllDates((current) => !current)}
                  >
                    {showAllDates ? "Show fewer" : `Show all ${occurrences.length} dates`}
                  </Button>
                </div>
              )}
            </>
          )}
        </Card>
      )}

      {activeTab === "waitlist" && (
        <Card p={20} className="min-w-0">
          <LaneHeader
            index="01"
            title="Waitlist"
            action={
              <Button
                variant="volt"
                size="sm"
                onClick={() => promoteMutation.mutate()}
                disabled={promoteMutation.isPending || waitingCount === 0}
              >
                Promote next
              </Button>
            }
          />
          {waitlistQuery.isLoading ? (
            <TableSkeleton />
          ) : waitlist.length === 0 ? (
            <p className="text-sm text-rally-subtle" data-testid="waitlist-empty">Waitlist is empty.</p>
          ) : (
            <WaitlistTable
              entries={waitlist}
              academyTimezone={session?.timezone ?? null}
              onSkip={(id) => skipWaitlistMutation.mutate(id)}
              onRemove={(id) =>
                setWaitlistRemoveTarget(waitlist.find((w) => w.waitlist_id === id) ?? null)
              }
            />
          )}
        </Card>
      )}

      {activeTab === "teaching-plan" && (
        <Card p={20} className="min-w-0">
          <LaneHeader index="01" title="Teaching plan" />
          <AdminTeachingPlan
            sessionId={sessionId}
            programId={rosterProgramId || null}
            timezone={session?.timezone ?? null}
          />
        </Card>
      )}

      {activeTab === "welcome" &&
        (session ? (
          <WelcomeEmailTab key={session.session_id} session={session} />
        ) : (
          <Card p={20}>
            <TableSkeleton />
          </Card>
        ))}

      <ConfirmActionDialog
        open={cancelSessionOpen}
        onOpenChange={setCancelSessionOpen}
        overline="Cancel session"
        title="Cancel this session for everyone?"
        subject={session ? `${session.title} · ${session.location}` : "This session"}
        consequence={
          <>
            <p>
              {activeEnrollments.length === 1
                ? "1 family loses its seat"
                : `${activeEnrollments.length} families lose their seats`}
              , and {waitlist.length === 1 ? "1 entry" : `${waitlist.length} entries`} on the
              waitlist {waitlist.length === 1 ? "is" : "are"} dropped. Billing for the session
              stops; invoices already raised stay and must be voided or credited by hand.
            </p>
            <p>Every enrolled family is emailed that the session was cancelled.</p>
            <p className="font-semibold text-rally-ink">This cannot be undone.</p>
          </>
        }
        confirmLabel="Cancel session"
        pending={cancelSessionMutation.isPending}
        onConfirm={() => {
          cancelSessionMutation.mutate();
          setCancelSessionOpen(false);
        }}
      />

      {waitlistRemoveTarget && (
        <ConfirmActionDialog
          open
          onOpenChange={(open) => !open && setWaitlistRemoveTarget(null)}
          overline={waitlistRemoveTarget.status === "offered" ? "Withdraw offer" : "Remove from waitlist"}
          title={
            waitlistRemoveTarget.status === "offered"
              ? "Withdraw the seat offered to this family?"
              : "Drop this student off the waitlist?"
          }
          subject={
            waitlistRemoveTarget.status === "offered"
              ? `${waitlistRemoveTarget.full_name} · seat offered`
              : `${waitlistRemoveTarget.full_name} · position ${waitlistRemoveTarget.position}`
          }
          consequence={
            waitlistRemoveTarget.status === "offered" ? (
              <>
                <p>
                  The seat being held for them is released and offered to the next family on the
                  waitlist, who is emailed. They can no longer confirm it.
                </p>
                <p>Nothing is invoiced — they were never enrolled.</p>
              </>
            ) : (
              <>
                <p>
                  They lose their place in the queue and will not be offered a seat when one opens.
                  Nothing is invoiced either way — a waitlisted student is never billed.
                </p>
                <p>Re-adding them later puts them at the back of the queue.</p>
              </>
            )
          }
          confirmLabel={
            waitlistRemoveTarget.status === "offered" ? "Withdraw offer" : "Remove from waitlist"
          }
          pending={removeWaitlistMutation.isPending}
          onConfirm={() => {
            removeWaitlistMutation.mutate(waitlistRemoveTarget.waitlist_id);
            setWaitlistRemoveTarget(null);
          }}
        />
      )}

      <AddToRosterDialog
        open={addOpen}
        onOpenChange={(next) => {
          setAddOpen(next);
          if (!next) setReEnrollTarget(null);
        }}
        sessionId={sessionId}
        prefill={
          reEnrollTarget
            ? {
                student_id: reEnrollTarget.student_id,
                parent_id: reEnrollTarget.parent_id,
                full_name: reEnrollTarget.full_name,
              }
            : null
        }
        onAdded={() => {
          setAddOpen(false);
          setReEnrollTarget(null);
          void queryClient.invalidateQueries({ queryKey: queryKeys.admin.enrollments(sessionId) });
          void queryClient.invalidateQueries({ queryKey: queryKeys.admin.sessionDetail(sessionId) });
          void queryClient.invalidateQueries({ queryKey: queryKeys.admin.sessions("upcoming") });
        }}
      />
      <SessionEditDialog
        open={editOpen}
        session={session}
        onOpenChange={setEditOpen}
        onSaved={(savedSession) => {
          setEditOpen(false);
          queryClient.setQueryData(queryKeys.admin.sessionDetail(sessionId), savedSession);
          queryClient.setQueryData<AdminSessionList | undefined>(
            queryKeys.admin.sessions("upcoming"),
            (current) =>
              current
                ? {
                    sessions: current.sessions.map((session) =>
                      session.session_id === savedSession.session_id ? savedSession : session,
                    ),
                  }
                : current,
          );
          void queryClient.invalidateQueries({ queryKey: queryKeys.admin.sessionDetail(sessionId) });
          void queryClient.invalidateQueries({ queryKey: queryKeys.admin.sessions("upcoming") });
        }}
      />
      <SessionAssistantsDialog
        open={assistantsOpen}
        session={session}
        onOpenChange={setAssistantsOpen}
        onSaved={(savedSession) => {
          setAssistantsOpen(false);
          queryClient.setQueryData(queryKeys.admin.sessionDetail(sessionId), savedSession);
          void queryClient.invalidateQueries({ queryKey: queryKeys.admin.sessionDetail(sessionId) });
          void queryClient.invalidateQueries({ queryKey: queryKeys.admin.sessions("upcoming") });
          // Assistants are re-synced onto future occurrences server-side.
          void queryClient.invalidateQueries({
            queryKey: queryKeys.admin.sessionOccurrences(sessionId),
          });
        }}
      />
      <CancelOccurrenceDialog
        occurrence={cancelTarget}
        timezone={session?.timezone ?? null}
        onClose={() => setCancelTarget(null)}
        onCancelled={() => {
          setCancelTarget(null);
          void queryClient.invalidateQueries({
            queryKey: queryKeys.admin.sessionOccurrences(sessionId),
          });
        }}
      />
      <OccurrenceAttendanceDialog
        occurrence={attendanceTarget}
        timezone={session?.timezone ?? null}
        studentNameById={studentNameById}
        onClose={() => setAttendanceTarget(null)}
      />
      <OccurrenceReplacementDialog
        sessionId={sessionId}
        open={replacementOpen}
        occurrence={occurrenceTarget}
        onClose={() => {
          setReplacementOpen(false);
          setOccurrenceTarget(null);
        }}
        onSaved={() => {
          setReplacementOpen(false);
          setOccurrenceTarget(null);
          void queryClient.invalidateQueries({
            queryKey: queryKeys.admin.sessionOccurrences(sessionId),
          });
        }}
      />
      <TransferEnrollmentDialog
        enrollment={transferTarget}
        currentSessionId={sessionId}
        currentSessionTitle={session?.title ?? ""}
        onClose={() => setTransferTarget(null)}
        onMoved={() => {
          setTransferTarget(null);
          void queryClient.invalidateQueries({ queryKey: queryKeys.admin.enrollments(sessionId) });
          void queryClient.invalidateQueries({ queryKey: queryKeys.admin.sessions("upcoming") });
        }}
      />
      <PauseEnrollmentDialog
        enrollment={pauseTarget}
        onClose={() => setPauseTarget(null)}
        onPaused={() => {
          setPauseTarget(null);
          void queryClient.invalidateQueries({ queryKey: queryKeys.admin.enrollments(sessionId) });
          void queryClient.invalidateQueries({ queryKey: queryKeys.admin.waitlist(sessionId) });
          void queryClient.invalidateQueries({ queryKey: queryKeys.admin.sessions("upcoming") });
        }}
      />
      <HoldEnrollmentDialog
        enrollmentId={holdTarget?.enrollment_id ?? null}
        studentName={holdTarget?.full_name ?? ""}
        onClose={() => setHoldTarget(null)}
        onHeld={() => {
          setHoldTarget(null);
          void queryClient.invalidateQueries({ queryKey: queryKeys.admin.enrollments(sessionId) });
          void queryClient.invalidateQueries({ queryKey: queryKeys.admin.waitlist(sessionId) });
          void queryClient.invalidateQueries({ queryKey: queryKeys.admin.sessions("upcoming") });
        }}
      />
      <ReturnFromHoldDialog
        enrollmentId={returnTarget?.enrollment_id ?? null}
        studentName={returnTarget?.full_name ?? ""}
        onClose={() => setReturnTarget(null)}
        onReturned={() => {
          setReturnTarget(null);
          void queryClient.invalidateQueries({ queryKey: queryKeys.admin.enrollments(sessionId) });
          void queryClient.invalidateQueries({ queryKey: queryKeys.admin.waitlist(sessionId) });
          void queryClient.invalidateQueries({ queryKey: queryKeys.admin.sessions("upcoming") });
        }}
      />
      <WithdrawalCreditDialog
        enrollment={withdrawalTarget}
        onClose={() => setWithdrawalTarget(null)}
        onApproved={() => {
          setWithdrawalTarget(null);
          void queryClient.invalidateQueries({
            queryKey: queryKeys.admin.enrollments(sessionId),
          });
        }}
      />
      <RemoveEnrollmentDialog
        enrollment={removeTarget}
        onClose={() => setRemoveTarget(null)}
        onRemoved={() => {
          setRemoveTarget(null);
          void queryClient.invalidateQueries({ queryKey: queryKeys.admin.enrollments(sessionId) });
          void queryClient.invalidateQueries({ queryKey: queryKeys.admin.sessions("upcoming") });
        }}
      />
    </section>
  );
}

/**
 * Who runs this session, on one line under the header: the lead coach and the
 * assistant coaches listed on it. Assistants see the session in their coach
 * app (attendance, skills, notes) and are never on payroll, so they are shown
 * as staff, not as a replacement or a pay line. Older cached rows predate the
 * field, hence the `?? []` guards.
 */
function CoachingStaffStrip({
  session,
  onEditAssistants,
}: {
  session: AdminSessionView;
  onEditAssistants: () => void;
}) {
  const ids = session.assistant_coach_ids ?? [];
  const names = session.assistant_coach_names ?? [];
  return (
    <div
      data-testid="session-staff"
      className="flex flex-wrap items-center gap-x-6 gap-y-2 rounded-xl border border-rally-line bg-white px-4 py-2.5 text-sm"
    >
      <span className="flex items-center gap-2">
        <span className="font-medium text-rally-muted">Lead coach</span>
        <span className="text-rally-ink" data-testid="session-lead-coach">
          {session.coach_name ?? session.coach_id}
        </span>
      </span>
      <span className="flex flex-wrap items-center gap-2">
        <span className="font-medium text-rally-muted">Assistants</span>
        <span className="flex flex-wrap items-center gap-2" data-testid="session-assistants">
          {ids.length === 0 ? (
            <span className="text-rally-subtle">None</span>
          ) : (
            ids.map((assistantId, index) => (
              <span
                key={assistantId}
                data-testid={`session-assistant-${assistantId}`}
                className="inline-flex items-center rounded-full border border-rally-line bg-rally-paper px-2.5 py-0.5 text-xs font-medium text-rally-ink"
              >
                {names[index] ?? assistantId}
              </span>
            ))
          )}
        </span>
      </span>
      <Button
        variant="secondary"
        size="sm"
        data-testid="edit-assistants"
        onClick={onEditAssistants}
      >
        Edit assistants
      </Button>
    </div>
  );
}
