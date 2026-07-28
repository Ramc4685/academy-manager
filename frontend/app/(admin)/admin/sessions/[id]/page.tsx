"use client";

/**
 * Admin session detail — Rally restyle.
 *
 * Preserves: roster table with pause/resume/move/remove, waitlist with
 * skip/remove + "promote next", add-to-roster dialog, transfer dialog,
 * cancel session.
 */

import { useMemo, useState } from "react";
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
} from "@/lib/api/admin";
import { getFullPathway, placeStudentInLevel } from "@/lib/api/curriculum";
import { queryKeys } from "@/lib/query/keys";

import { Button } from "@/components/ds/button";
import { Card } from "@/components/ds/card";
import { Icon } from "@/components/ds/icons";
import { LaneHeader } from "@/components/ds/lane";
import { TableSkeleton } from "@/components/ds/skeleton";
import { AdminTeachingPlan } from "@/components/teaching/admin-teaching-plan";

import { AddToRosterDialog, PauseEnrollmentDialog, RemoveEnrollmentDialog, TransferEnrollmentDialog, WithdrawalCreditDialog } from "./dialogs";
import { formatCurrencyCents, sessionTimeRange } from "./format";
import { RosterMetrics, RosterTable } from "./RosterPanel";
import { OccurrenceReplacementDialog, ReplacementCoachTable, SessionEditDialog } from "./SessionEditing";
import { WaitlistTable } from "./WaitlistTable";

const DETAIL_TABS = [
  { id: "roster", label: "Roster" },
  { id: "waitlist", label: "Waitlist" },
  { id: "teaching-plan", label: "Teaching plan" },
] as const;
type DetailTab = (typeof DETAIL_TABS)[number]["id"];

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
    onSuccess: () => {
      window.location.href = "/admin/sessions";
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
            onEdit={setOccurrenceTarget}
          />
        )}
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
            index="02"
            title="Roster"
            action={
              session && (
                <span className="font-mono text-sm font-semibold tabular-nums text-rally-muted">
                  {enrollments.length}/{session.capacity}
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
              onResume={(id) =>
                resumeEnrollment(id).then(() => {
                  void queryClient.invalidateQueries({
                    queryKey: queryKeys.admin.enrollments(sessionId),
                  });
                  void queryClient.invalidateQueries({ queryKey: queryKeys.admin.waitlist(sessionId) });
                  void queryClient.invalidateQueries({ queryKey: queryKeys.admin.sessions("upcoming") });
                })
              }
              onTransfer={(enrollment) => setTransferTarget(enrollment)}
              onWithdraw={(enrollment) => setWithdrawalTarget(enrollment)}
            />
          )}
        </Card>
      )}

      {activeTab === "waitlist" && (
        <Card p={20} className="min-w-0">
          <LaneHeader
            index="03"
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
              onSkip={(id) =>
                skipWaitlistEntry(id).then(() =>
                  queryClient.invalidateQueries({ queryKey: queryKeys.admin.waitlist(sessionId) })
                )
              }
              onRemove={(id) => {
                if (confirm("Remove from waitlist?")) {
                  deleteWaitlistEntry(id).then(() =>
                    queryClient.invalidateQueries({ queryKey: queryKeys.admin.waitlist(sessionId) })
                  );
                }
              }}
            />
          )}
        </Card>
      )}

      {activeTab === "teaching-plan" && (
        <Card p={20} className="min-w-0">
          <LaneHeader index="04" title="Teaching plan" />
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
