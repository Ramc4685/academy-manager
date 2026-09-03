"use client";

/**
 * Admin session detail — Rally restyle.
 *
 * Preserves: roster table with pause/resume/move/remove, waitlist with
 * skip/remove + "promote next", add-to-roster dialog, transfer dialog,
 * cancel session.
 */

import { Fragment, useMemo, useState } from "react";
import Link from "next/link";
import { useParams } from "next/navigation";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";

import {
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
} from "@/lib/api/admin";
import { getFullPathway, placeStudentInLevel } from "@/lib/api/curriculum";
import { queryKeys } from "@/lib/query/keys";

import { Button } from "@/components/ds/button";
import { Card } from "@/components/ds/card";
import { Icon } from "@/components/ds/icons";
import { LaneHeader } from "@/components/ds/lane";
import { TableSkeleton } from "@/components/ds/skeleton";
import { AdminTeachingPlan } from "@/components/teaching/admin-teaching-plan";
import { AnnouncementsPanel } from "@/components/announcements/AnnouncementsPanel";

import { AddToRosterDialog, PauseEnrollmentDialog, RemoveEnrollmentDialog, TransferEnrollmentDialog, WithdrawalCreditDialog } from "./dialogs";
import {
  formatArrivalMinutes,
  formatCurrencyCents,
  hasCommunicationPack,
  sessionTimeRange,
} from "./format";
import { RosterMetrics, RosterTable } from "./RosterPanel";
import { OccurrenceReplacementDialog, ReplacementCoachTable, SessionEditDialog } from "./SessionEditing";
import { WaitlistTable } from "./WaitlistTable";

const DETAIL_TABS = [
  { id: "roster", label: "Roster" },
  { id: "waitlist", label: "Waitlist" },
  { id: "teaching-plan", label: "Teaching plan" },
] as const;
type DetailTab = (typeof DETAIL_TABS)[number]["id"];

const CANCEL_FAILED_FALLBACK = "Could not cancel session.";

function cancelErrorMessage(err: unknown): string {
  const reason = err instanceof Error ? err.message.trim() : "";
  return reason ? `Could not cancel session: ${reason}` : CANCEL_FAILED_FALLBACK;
}

export default function AdminSessionDetailPage() {
  const params = useParams();
  const sessionId = params.id as string;
  const queryClient = useQueryClient();
  const [addOpen, setAddOpen] = useState(false);
  const [editOpen, setEditOpen] = useState(false);
  const [pauseTarget, setPauseTarget] = useState<AdminEnrollmentView | null>(null);
  const [removeTarget, setRemoveTarget] = useState<AdminEnrollmentView | null>(null);
  const [transferTarget, setTransferTarget] = useState<AdminEnrollmentView | null>(null);
  const [withdrawalTarget, setWithdrawalTarget] = useState<AdminEnrollmentView | null>(null);
  const [occurrenceTarget, setOccurrenceTarget] = useState<AdminSessionOccurrenceView | null>(null);
  const [replacementOpen, setReplacementOpen] = useState(false);
  const [activeTab, setActiveTab] = useState<DetailTab>("roster");
  const [cancelError, setCancelError] = useState<string | null>(null);

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

  const usersQuery = useQuery({
    queryKey: queryKeys.admin.users(),
    queryFn: () => listAdminUsers(),
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
    },
  });

  const session = sessionsQuery.data ?? null;
  const enrollments = useMemo(
    () => enrollmentsQuery.data?.enrollments ?? [],
    [enrollmentsQuery.data?.enrollments],
  );
  const occurrences = occurrencesQuery.data?.occurrences ?? [];
  const replacementOccurrences = occurrences.filter((occurrence) => Boolean(occurrence.actual_coach_id));
  const userNameById = new Map(
    (usersQuery.data?.users ?? []).map((user) => [user.user_id, user.display_name || user.email])
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
        <div className="flex gap-2">
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
            onClick={() => {
              if (confirm("Cancel this session? This cannot be undone.")) {
                cancelSessionMutation.mutate();
              }
            }}
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

      {/* Replacement coaches */}
      <Card p={20} className="min-w-0">
        <LaneHeader
          index="01"
          title="Replacement coaches"
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
        ) : replacementOccurrences.length === 0 ? (
          <p className="text-sm text-rally-subtle">No replacement coaches added.</p>
        ) : (
          <ReplacementCoachTable
            occurrences={replacementOccurrences}
            userNameById={userNameById}
            timezone={session?.timezone ?? null}
            onEdit={setOccurrenceTarget}
          />
        )}
      </Card>

      {/* Communication pack (#613) */}
      <Card p={20} className="min-w-0">
        <LaneHeader
          index="02"
          title="Communication pack"
          action={
            // Distinct accessible name from the header's "Edit session": both
            // open the same dialog, but two identically-named buttons on one
            // page are ambiguous for screen readers and for role locators (#630).
            <Button variant="secondary" size="sm" onClick={() => setEditOpen(true)}>
              Edit communication pack
            </Button>
          }
        />
        {session ? <CommunicationPackCard session={session} /> : <TableSkeleton />}
      </Card>

      <div className="flex flex-wrap gap-2 border-b border-rally-line">
        {DETAIL_TABS.map((tab) => (
          <button
            key={tab.id}
            type="button"
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
            index="03"
            title="Roster"
            action={
              session && (
                <span className="font-mono text-sm font-semibold tabular-nums text-rally-muted">
                  {enrollments.filter((e) => e.status === "active").length}/{session.capacity}
                </span>
              )
            }
          />
          {session && (
            <RosterMetrics enrollments={enrollments} capacity={session.capacity} />
          )}
          {enrollmentsQuery.isLoading ? (
            <TableSkeleton />
          ) : enrollments.length === 0 ? (
            <p className="text-sm text-rally-subtle" data-testid="roster-empty">No enrolled students.</p>
          ) : (
            <RosterTable
              enrollments={enrollments}
              sessionId={sessionId}
              pathwayLevels={pathwayLevels}
              updatingPlacementStudentId={
                placementMutation.isPending ? placementMutation.variables?.studentId : null
              }
              onPathwayLevelChange={(enrollment, levelId) =>
                placementMutation.mutate({
                  studentId: enrollment.student_id,
                  programId: enrollment.pathway_program_id,
                  levelId,
                })
              }
              onDelete={(enrollment) => setRemoveTarget(enrollment)}
              onPause={(enrollment) => setPauseTarget(enrollment)}
              onResume={(id) => resumeMutation.mutate(id)}
              onTransfer={(enrollment) => setTransferTarget(enrollment)}
              onWithdraw={(enrollment) => setWithdrawalTarget(enrollment)}
            />
          )}
        </Card>
      )}

      {activeTab === "roster" && (
        <Card p={20} className="min-w-0">
          <LaneHeader index="04" title="Announcements" />
          <AnnouncementsPanel persona="admin" sessionId={sessionId} />
        </Card>
      )}

      {activeTab === "waitlist" && (
        <Card p={20} className="min-w-0">
          <LaneHeader
            index="05"
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
              onSkip={(id) => skipWaitlistMutation.mutate(id)}
              onRemove={(id) => {
                if (confirm("Remove from waitlist?")) {
                  removeWaitlistMutation.mutate(id);
                }
              }}
            />
          )}
        </Card>
      )}

      {activeTab === "teaching-plan" && (
        <Card p={20} className="min-w-0">
          <LaneHeader index="06" title="Teaching plan" />
          <AdminTeachingPlan sessionId={sessionId} programId={rosterProgramId || null} />
        </Card>
      )}

      <AddToRosterDialog
        open={addOpen}
        onOpenChange={setAddOpen}
        sessionId={sessionId}
        onAdded={() => {
          setAddOpen(false);
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
 * Read-only view of the per-session communication pack (#613).
 *
 * Only populated rows render — an empty definition list row would read as
 * "configured but blank", which is exactly the thing the welcome email must
 * never do either.
 */
function CommunicationPackCard({ session }: { session: AdminSessionView }) {
  if (!hasCommunicationPack(session)) {
    return (
      <p className="text-sm text-rally-subtle" data-testid="communication-pack-empty">
        No communication pack configured. Add venue, arrival and group details from Edit
        communication pack.
      </p>
    );
  }

  const rows: Array<[string, string]> = [
    ["Venue address", session.venue_address ?? ""],
    ["Parking", session.parking_notes ?? ""],
    ["What to bring", session.what_to_bring ?? ""],
    ["Arrival", formatArrivalMinutes(session.arrival_minutes_before)],
    ["Coach contact", session.coach_contact_policy ?? ""],
    ["Absences & make-ups", session.absence_policy ?? ""],
  ].filter(([, value]) => value.trim() !== "") as Array<[string, string]>;

  return (
    <div className="space-y-4" data-testid="communication-pack">
      {session.whatsapp_group_link ? (
        <a
          href={session.whatsapp_group_link}
          target="_blank"
          rel="noopener noreferrer"
          className="inline-flex min-h-10 items-center rounded-md bg-rally-cobalt-600 px-4 text-sm font-semibold text-white hover:bg-rally-cobalt-700"
        >
          Open WhatsApp group
        </a>
      ) : null}
      {rows.length > 0 ? (
        <dl className="grid gap-3 sm:grid-cols-[200px_minmax(0,1fr)]">
          {rows.map(([label, value]) => (
            <Fragment key={label}>
              <dt className="text-sm font-medium text-rally-muted">{label}</dt>
              <dd className="whitespace-pre-line text-sm text-rally-ink">{value}</dd>
            </Fragment>
          ))}
        </dl>
      ) : null}
    </div>
  );
}
