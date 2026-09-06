"use client";

import Link from "next/link";
import { use, useCallback, useEffect, useMemo, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { ulid } from "ulid";

import {
  bulkMarkAttendance,
  correctAttendance,
  createProgressNote,
  getCoachToday,
  listProgressNotes,
  markAttendance,
  setProgressNoteVisibility,
  type AttendanceStatus,
  type CoachRosterEntry,
  type NoteVisibility,
  type ProgressNote,
} from "@/lib/api/coach";
import { AnnouncementsPanel } from "@/components/announcements/AnnouncementsPanel";
import { BillingPreviewDrawer } from "@/components/coach/billing-preview-drawer";
import { useIsAssistantCoach } from "@/components/coach/coach-surface-context";
import { SessionDetailTabs } from "@/components/coach/SessionDetailTabs";
import { Chip } from "@/components/ds/chip";
import { queueMark, queuedMarksFor, type QueuedMark } from "@/lib/offline/attendance-queue";
import { onSync, syncNow } from "@/lib/offline/sync";
import { queryKeys } from "@/lib/query/keys";
import { useOnline } from "@/lib/pwa/online";
import { formatSessionTimeRange } from "@/lib/time/session-time";

const CLIENT_APP_VERSION = "v2-w1b";

function todayISO(): string {
  const now = new Date();
  const year = now.getFullYear();
  const month = String(now.getMonth() + 1).padStart(2, "0");
  const day = String(now.getDate()).padStart(2, "0");
  return `${year}-${month}-${day}`;
}

interface PageProps {
  params: Promise<{ id: string }>;
  searchParams: Promise<{ date?: string }>;
}

type MarkStatus = "present" | "absent";

interface OptimisticEntry {
  student_id: string;
  status: MarkStatus | null;
  pending: boolean;
  error?: string;
  /** True when the error came back from the offline sync: the mark sits in the tray. */
  needsReview?: boolean;
}

// Domain rejections come back as 409 with a machine code (see
// backend/v2/shared/http/errors.py). Each one is a different coach action —
// none of them is a connectivity problem, so never describe them as one.
const ATTENDANCE_ERROR_MESSAGES: Record<string, string> = {
  "Coaching.ConflictAttendanceExists":
    "Attendance for this student was already recorded (maybe from another device). Refresh to see it.",
  "Coaching.StudentNotEnrolled":
    "This student isn't actively enrolled in this session, so attendance can't be saved. Ask the admin to check their roster status.",
  "Coaching.SessionNotAssigned":
    "This session isn't assigned to your coach account for today.",
  "Coaching.SessionCancelled": "This session occurrence was cancelled.",
  "Coaching.CorrectionWindowExpired":
    "This mark is older than 48 hours, so it can only be changed by an admin.",
  "Coaching.AttendanceNotFound":
    "No recorded mark was found to change. Refresh and try again.",
};

function formatApiError(err: unknown): string {
  const apiError = err as { status?: number; code?: string; message?: string };
  if (apiError.code && ATTENDANCE_ERROR_MESSAGES[apiError.code]) {
    return ATTENDANCE_ERROR_MESSAGES[apiError.code];
  }
  if (apiError.status === 404) {
    return "This session or student is not available to your coach account.";
  }
  if (apiError.status === 409) {
    return apiError.message || "Attendance could not be saved because of a conflict. Refresh and retry.";
  }
  if (typeof apiError.status === "number" && apiError.status >= 500) {
    return "The server could not save attendance. It has been logged — retry in a moment.";
  }
  return "Could not save attendance. Check your connection and retry.";
}

/** Plain-language reason for a queued mark that the sync moved to the tray. */
function formatSyncReason(code: string | undefined): string {
  if (code && ATTENDANCE_ERROR_MESSAGES[code]) return ATTENDANCE_ERROR_MESSAGES[code];
  return "This queued mark couldn't be saved.";
}

export default function SessionDetailPage({ params, searchParams }: PageProps) {
  const { id } = use(params);
  const { date: dateParam } = use(searchParams);
  const decodedId = decodeURIComponent(id);
  const queryClient = useQueryClient();
  const online = useOnline();
  // Assistant coaches mark attendance, update skills and write notes here;
  // announcements and billing previews are lead-coach surfaces (the BFF 404s
  // them for assistants), so they are not rendered at all. They may write
  // notes but never share them with parents.
  const assistant = useIsAssistantCoach();

  const date = dateParam ?? todayISO();
  const { data: today, isLoading, isError } = useQuery({
    queryKey: queryKeys.coach.today(date),
    queryFn: () => getCoachToday(date),
    staleTime: 5 * 60 * 1000,
  });

  const session = useMemo(
    () =>
      today?.sessions.find(
        (s) => s.occurrence_id === decodedId || s.session_id === decodedId,
      ),
    [today, decodedId],
  );
  const roster: CoachRosterEntry[] = session?.roster ?? [];
  const sessionId = session?.session_id ?? decodedId;
  const occurrenceId = session?.occurrence_id ?? decodedId;

  const [localMarks, setLocalMarks] = useState<Record<string, OptimisticEntry>>(
    {},
  );
  // Marks saved on this phone while offline, waiting for the sync
  // (lib/offline/attendance-queue.ts). Hydrated from IndexedDB.
  const [queuedMarks, setQueuedMarks] = useState<Record<string, QueuedMark>>({});
  const [queueingAll, setQueueingAll] = useState(false);
  // noteOpen tracks which student has the inline note box open
  const [noteOpen, setNoteOpen] = useState<string | null>(null);
  const [noteTexts, setNoteTexts] = useState<Record<string, string>>({});
  const [noteShare, setNoteShare] = useState<Record<string, boolean>>({});
  const [billingOpen, setBillingOpen] = useState<string | null>(null);

  const progressNotesKey = queryKeys.coach.progressNotes(sessionId);
  const { data: notesData } = useQuery({
    queryKey: progressNotesKey,
    queryFn: () => listProgressNotes(sessionId),
    enabled: online && Boolean(session),
    staleTime: 60 * 1000,
  });
  const notesByStudent = useMemo(() => {
    const out: Record<string, ProgressNote[]> = {};
    for (const note of notesData?.notes ?? []) {
      (out[note.student_id] ??= []).push(note);
    }
    for (const list of Object.values(out)) {
      list.sort((a, b) => b.created_at.localeCompare(a.created_at));
    }
    return out;
  }, [notesData]);

  // Hydrate queued marks on mount and whenever connectivity flips, so a
  // reload while offline still shows what is waiting on this phone.
  const sessionOccurrenceId = session?.occurrence_id;
  const hydrateQueued = useCallback(() => {
    if (!sessionOccurrenceId) return;
    void queuedMarksFor(sessionOccurrenceId)
      .then((marks) => setQueuedMarks(marks))
      .catch(() => undefined);
  }, [sessionOccurrenceId]);
  useEffect(() => {
    hydrateQueued();
  }, [hydrateQueued, online]);

  // Follow the sync: a replayed mark becomes a saved one; a 4xx moves it to
  // the tray and the row says so.
  useEffect(() => {
    if (!sessionOccurrenceId) return;
    const occ = sessionOccurrenceId;
    return onSync((event) => {
      if (event.kind === "finished") {
        hydrateQueued();
        void queryClient.invalidateQueries({ queryKey: queryKeys.coach.today(date) });
        return;
      }
      if (event.kind !== "succeeded" && event.kind !== "needs_review") return;
      const payload = event.mutation.payload as {
        occurrence_id?: string;
        student_id?: string;
        status?: AttendanceStatus;
      };
      if (payload.occurrence_id !== occ || !payload.student_id) return;
      const student_id = payload.student_id;
      setQueuedMarks((prev) => {
        if (!(student_id in prev)) return prev;
        const next = { ...prev };
        delete next[student_id];
        return next;
      });
      if (event.kind === "succeeded") {
        setLocalMarks((m) => ({
          ...m,
          [student_id]: {
            student_id,
            status: (payload.status as MarkStatus | undefined) ?? null,
            pending: false,
          },
        }));
        void queryClient.invalidateQueries({ queryKey: queryKeys.coach.today(date) });
      } else {
        setLocalMarks((m) => ({
          ...m,
          [student_id]: {
            student_id,
            status: null,
            pending: false,
            error: formatSyncReason(event.mutation.error?.code),
            needsReview: true,
          },
        }));
      }
    });
  }, [sessionOccurrenceId, date, queryClient, hydrateQueued]);

  const noteMutation = useMutation({
    mutationFn: ({
      studentId,
      body,
      visibility,
    }: {
      studentId: string;
      body: string;
      visibility: NoteVisibility;
    }) =>
      createProgressNote(sessionId, {
        student_id: studentId,
        body,
        visibility,
      }),
    onSuccess: (_data, { studentId }) => {
      setNoteTexts((t) => ({ ...t, [studentId]: "" }));
      setNoteShare((s) => ({ ...s, [studentId]: false }));
      setNoteOpen(null);
      void queryClient.invalidateQueries({ queryKey: progressNotesKey });
    },
  });

  const noteVisibilityMutation = useMutation({
    mutationFn: ({ noteId, visibility }: { noteId: string; visibility: NoteVisibility }) =>
      setProgressNoteVisibility(sessionId, noteId, visibility),
    onSettled: () => {
      void queryClient.invalidateQueries({ queryKey: progressNotesKey });
    },
  });

  // Changing an existing mark goes through the correction endpoint (#517):
  // marks are write-once, so re-POSTing always 409s (#646).
  const correctionMutation = useMutation({
    mutationFn: async (vars: { student_id: string; status: AttendanceStatus }) =>
      correctAttendance(occurrenceId, vars.student_id, {
        status: vars.status,
        reason: "coach correction from roster",
      }),
    onMutate: ({ student_id, status }) => {
      setLocalMarks((m) => ({
        ...m,
        [student_id]: { student_id, status: status as MarkStatus, pending: true },
      }));
    },
    onSuccess: (res) => {
      setLocalMarks((m) => ({
        ...m,
        [res.student_id]: {
          student_id: res.student_id,
          status: res.status as MarkStatus,
          pending: false,
        },
      }));
      void queryClient.invalidateQueries({ queryKey: queryKeys.coach.today(date) });
    },
    onError: (err: unknown, vars) => {
      setLocalMarks((m) => ({
        ...m,
        [vars.student_id]: {
          student_id: vars.student_id,
          status: null,
          pending: false,
          error: formatApiError(err),
        },
      }));
    },
  });

  const attendanceMutation = useMutation({
    mutationFn: async (vars: {
      student_id: string;
      status: AttendanceStatus;
    }) =>
      markAttendance({
        mutation_id: ulid(),
        occurrence_id: occurrenceId,
        session_id: sessionId,
        student_id: vars.student_id,
        status: vars.status,
        client_app_version: CLIENT_APP_VERSION,
        marked_at_client: new Date().toISOString(),
      }),
    onMutate: ({ student_id, status }) => {
      setLocalMarks((m) => ({
        ...m,
        [student_id]: {
          student_id,
          status: status as MarkStatus,
          pending: true,
        },
      }));
    },
    onSuccess: (res) => {
      setLocalMarks((m) => ({
        ...m,
        [res.student_id]: {
          student_id: res.student_id,
          status: res.status as MarkStatus,
          pending: false,
        },
      }));
    },
    onError: (err: unknown, vars) => {
      setLocalMarks((m) => ({
        ...m,
        [vars.student_id]: {
          student_id: vars.student_id,
          status: null,
          pending: false,
          error: formatApiError(err),
        },
      }));
      // "Already recorded" means the server HAS a mark for this student —
      // the coach's tap was a change, not a first mark. Apply it as a
      // correction instead of leaving an error (#646).
      if ((err as { code?: string }).code === "Coaching.ConflictAttendanceExists") {
        correctionMutation.mutate({ student_id: vars.student_id, status: vars.status });
      }
    },
  });

  const bulkAttendanceMutation = useMutation({
    mutationFn: async (studentIds: string[]) =>
      bulkMarkAttendance(occurrenceId, {
        mutation_id: ulid(),
        session_id: sessionId,
        entries: studentIds.map((student_id) => ({
          student_id,
          status: "present" as const,
        })),
      }),
    onMutate: (studentIds) => {
      setLocalMarks((m) => {
        const next = { ...m };
        for (const student_id of studentIds) {
          next[student_id] = { student_id, status: "present", pending: true };
        }
        return next;
      });
    },
    onSuccess: (res) => {
      setLocalMarks((m) => {
        const next = { ...m };
        for (const r of res.results) {
          next[r.student_id] = {
            student_id: r.student_id,
            status: r.status as MarkStatus,
            pending: false,
          };
        }
        return next;
      });
    },
    onError: (err: unknown, studentIds) => {
      const conflict = (err as { status?: number }).status === 409;
      setLocalMarks((m) => {
        const next = { ...m };
        for (const student_id of studentIds) {
          if (conflict) {
            // Server truth wins after the refetch below; a lingering local
            // null entry would mask the already-recorded mark.
            delete next[student_id];
          } else {
            next[student_id] = {
              student_id,
              status: null,
              pending: false,
              error: formatApiError(err),
            };
          }
        }
        return next;
      });
      // 409 = someone in the batch is already marked server-side. The offline
      // caches (SW stale-while-revalidate + persisted query cache) can lag, so
      // refetch the truth; the roster then shows real marks and a retry only
      // sends the genuinely unmarked students.
      if (conflict) {
        void queryClient.invalidateQueries({
          queryKey: queryKeys.coach.today(date),
          refetchType: "all",
        });
      }
    },
  });

  /** A mark the server already holds (optimistic-confirmed or hydrated). */
  const hasServerMark = (student: CoachRosterEntry): boolean =>
    Boolean(localMarks[student.student_id]?.status) || Boolean(student.attendance_status);

  const unmarkedStudentIds = roster
    .filter(
      (student) => !hasServerMark(student) && !queuedMarks[student.student_id],
    )
    .map((student) => student.student_id);
  const queuedCount = Object.keys(queuedMarks).length;
  const anySavedMark = roster.some(hasServerMark);

  // Save a first mark on this phone (offline, or while an earlier queued mark
  // for the same student is still waiting — one queued mark per student).
  async function queueLocally(student_id: string, status: AttendanceStatus): Promise<void> {
    try {
      const m = await queueMark({
        occurrence_id: occurrenceId,
        session_id: sessionId,
        student_id,
        status,
        client_app_version: CLIENT_APP_VERSION,
      });
      setQueuedMarks((prev) => ({ ...prev, [student_id]: { status, mutation_id: m.mutation_id } }));
      setLocalMarks((m2) => {
        if (!m2[student_id]?.error) return m2;
        const next = { ...m2 };
        delete next[student_id];
        return next;
      });
    } catch {
      setLocalMarks((m) => ({
        ...m,
        [student_id]: {
          student_id,
          status: null,
          pending: false,
          error: "Couldn't save this mark on this phone. Try again when you're back online.",
        },
      }));
    }
  }

  function handleMark(student: CoachRosterEntry, status: AttendanceStatus): void {
    const queued = queuedMarks[student.student_id];
    if (queued) {
      // Policy case #1: the second tap rewrites the queued mark in place.
      // Offline, tapping the status already queued changes nothing. Online,
      // any tap on a still-queued mark is the coach asking for it to be sent
      // now — the rewrite resets the sync's retry budget (attendance-queue.ts)
      // so a mark the sync paused after repeated failures goes out again.
      if (!online && queued.status === status) return;
      void queueLocally(student.student_id, status).then(() => {
        if (online) void syncNow();
      });
      return;
    }
    const existing =
      localMarks[student.student_id]?.status ?? student.attendance_status ?? null;
    if (existing === status) return; // already recorded as this
    if (!online) {
      // Corrections are not replayable by the queue; the row is disabled.
      if (existing) return;
      void queueLocally(student.student_id, status);
      return;
    }
    if (existing) {
      // A mark exists: this tap is a change → correction (#646).
      correctionMutation.mutate({ student_id: student.student_id, status });
      return;
    }
    attendanceMutation.mutate({ student_id: student.student_id, status });
  }

  async function handleMarkAll(): Promise<void> {
    if (online) {
      bulkAttendanceMutation.mutate(unmarkedStudentIds);
      return;
    }
    setQueueingAll(true);
    try {
      for (const student_id of unmarkedStudentIds) {
        await queueLocally(student_id, "present");
      }
    } finally {
      setQueueingAll(false);
    }
  }

  if (isLoading)
    return <div className="text-neutral-500">Loading session…</div>;

  if (isError) {
    return (
      <div role="alert" className="rounded-md border border-red-200 bg-red-50 p-4 text-sm text-red-800">
        Could not load session.{" "}
        <Link className="underline" href="/coach/sessions">
          Back to sessions
        </Link>
      </div>
    );
  }

  if (!session) {
    return (
      <div className="rounded-md border border-amber-200 bg-amber-50 p-4 text-sm text-amber-800">
        Session not found.{" "}
        <Link className="underline" href="/coach/sessions">
          Back to sessions
        </Link>
      </div>
    );
  }

  const markAllPending = bulkAttendanceMutation.isPending || queueingAll;

  return (
    <section data-testid="session-detail">
      <header className="mb-4 flex flex-col gap-3 sm:flex-row sm:items-start sm:justify-between">
        <div>
          <h1
            className="text-xl font-semibold"
            style={{ color: "var(--rally-ink)" }}
          >
            {session.title}
          </h1>
          <p className="text-sm" style={{ color: "var(--rally-muted)" }}>
            {session.location} ·{" "}
            {formatSessionTimeRange(session.start_at, session.end_at, session.timezone)}
          </p>
          {session.coach_name && (
            <p
              className="text-sm"
              style={{ color: "var(--rally-muted)" }}
              data-testid="session-coach-name"
            >
              Coach: {session.coach_name}
            </p>
          )}
        </div>
      </header>

      <SessionDetailTabs
        attendanceSkillsId={session.occurrence_id}
        progressSessionId={session.session_id}
        date={date}
        active="attendance"
      />

      {!online && (
        <div
          data-testid="offline-indicator"
          role="status"
          className="mb-4 rounded-md border border-amber-200 bg-amber-50 p-3 text-sm text-amber-800"
        >
          <p>
            You&apos;re offline — marks are saved on this phone and sent when you
            reconnect.
          </p>
          {anySavedMark && (
            <p data-testid="offline-write-blocked" className="mt-1 text-xs">
              Saved marks can be changed when you&apos;re back online.
            </p>
          )}
        </div>
      )}

      {/* Attendance roster */}
      <section>
        <div className="mb-2 flex flex-wrap items-center justify-between gap-2">
          <div className="flex items-center gap-2">
            <h2
              className="text-sm font-semibold uppercase tracking-wide"
              style={{ color: "var(--rally-muted)" }}
            >
              Attendance · {roster.length} students
            </h2>
            {queuedCount > 0 && (
              <span
                data-testid="queued-count"
                className="rounded-full border border-amber-200 bg-amber-50 px-2 py-0.5 text-xs font-semibold text-amber-800"
              >
                {queuedCount} queued
              </span>
            )}
          </div>
          {roster.length > 0 && (
            <button
              data-testid="mark-all-present"
              disabled={markAllPending || unmarkedStudentIds.length === 0}
              onClick={() => void handleMarkAll()}
              className="min-h-[44px] rounded-md bg-green-600 px-3 py-1 text-xs font-semibold text-white transition-colors hover:bg-green-700 disabled:opacity-50"
            >
              {markAllPending
                ? "Marking all…"
                : unmarkedStudentIds.length === 0
                  ? "All marked"
                  : `Mark all present (${unmarkedStudentIds.length})`}
            </button>
          )}
        </div>
        {roster.length === 0 ? (
          <p className="text-sm" style={{ color: "var(--rally-muted)" }}>
            No students enrolled.
          </p>
        ) : (
          <ul className="space-y-2" data-testid="roster">
            {roster.map((student) => (
              <RosterRow
                key={student.student_id}
                student={student}
                sessionId={session.session_id}
                local={localMarks[student.student_id]}
                queued={queuedMarks[student.student_id]}
                online={online}
                noteOpen={noteOpen === student.student_id}
                noteText={noteTexts[student.student_id] ?? ""}
                noteShare={noteShare[student.student_id] ?? false}
                notes={notesByStudent[student.student_id] ?? []}
                assistant={assistant}
                onMark={(status) => handleMark(student, status)}
                onToggleNote={() =>
                  setNoteOpen((prev) =>
                    prev === student.student_id ? null : student.student_id,
                  )
                }
                onNoteChange={(text) =>
                  setNoteTexts((t) => ({ ...t, [student.student_id]: text }))
                }
                onNoteShareChange={(share) =>
                  setNoteShare((s) => ({ ...s, [student.student_id]: share }))
                }
                onNoteSave={(body, visibility) =>
                  noteMutation.mutate({ studentId: student.student_id, body, visibility })
                }
                noteSaving={noteMutation.isPending}
                onNoteVisibility={(noteId, visibility) =>
                  noteVisibilityMutation.mutate({ noteId, visibility })
                }
                noteVisibilityPendingId={
                  noteVisibilityMutation.isPending
                    ? noteVisibilityMutation.variables?.noteId ?? null
                    : null
                }
                showBilling={!assistant}
                billingOpen={billingOpen === student.student_id}
                onToggleBilling={() =>
                  setBillingOpen((prev) =>
                    prev === student.student_id ? null : student.student_id,
                  )
                }
              />
            ))}
          </ul>
        )}
      </section>

      {/*
        Announcements are SESSION-scoped, but this route's id may be an
        occurrence_id (see the SessionDetailTabs docstring and the
        `occurrence_id || session_id` lookup above). Passing `decodedId` would
        404 on every recurring session, so the resolved `session.session_id`
        is what goes down.
      */}
      {!assistant && (
        <section className="mt-6">
          <h2
            className="mb-2 text-sm font-semibold uppercase tracking-wide"
            style={{ color: "var(--rally-muted)" }}
          >
            Announcements
          </h2>
          <AnnouncementsPanel persona="coach" sessionId={session.session_id} />
        </section>
      )}
    </section>
  );
}

const MARK_BUTTON_BASE =
  "min-h-[44px] min-w-[44px] flex-1 rounded-md border px-3 py-1 text-sm font-medium transition-colors disabled:opacity-50 sm:flex-none sm:min-w-[88px]";
const SECONDARY_BUTTON_BASE =
  "inline-flex min-h-[44px] flex-1 items-center justify-center rounded-md border px-3 py-1 text-xs font-medium transition-colors disabled:opacity-50 sm:flex-none";

function RosterRow({
  student,
  sessionId,
  local,
  queued,
  online,
  noteOpen,
  noteText,
  noteShare,
  notes,
  assistant,
  onMark,
  onToggleNote,
  onNoteChange,
  onNoteShareChange,
  onNoteSave,
  noteSaving,
  onNoteVisibility,
  noteVisibilityPendingId,
  showBilling,
  billingOpen,
  onToggleBilling,
}: {
  student: CoachRosterEntry;
  sessionId: string;
  local?: OptimisticEntry;
  queued?: QueuedMark;
  online: boolean;
  noteOpen: boolean;
  noteText: string;
  noteShare: boolean;
  notes: ProgressNote[];
  /** Assistant coaches write notes but cannot share them or change visibility. */
  assistant: boolean;
  onMark: (status: AttendanceStatus) => void;
  onToggleNote: () => void;
  onNoteChange: (text: string) => void;
  onNoteShareChange: (share: boolean) => void;
  onNoteSave: (body: string, visibility: NoteVisibility) => void;
  noteSaving: boolean;
  onNoteVisibility: (noteId: string, visibility: NoteVisibility) => void;
  noteVisibilityPendingId: string | null;
  /** False for assistant coaches: the billing preview is lead-only. */
  showBilling: boolean;
  billingOpen: boolean;
  onToggleBilling: () => void;
}) {
  // Optimistic local state wins; then a mark queued on this phone; otherwise
  // fall back to the server-recorded mark so a reload doesn't render a marked
  // class as unmarked.
  // A local entry with status=null is a failed attempt; fall through to the
  // server-hydrated mark so an "already recorded" conflict still shows what
  // is recorded instead of blanking the row (#638).
  const marked = local?.status ?? queued?.status ?? student.attendance_status ?? null;
  const savedOnServer = Boolean(local?.status) || Boolean(student.attendance_status);
  // Offline, only first marks can be queued: a saved mark would need a
  // correction, which the queue cannot replay (docs/offline-policy.md).
  const markDisabled = Boolean(local?.pending) || (!online && savedOnServer);
  const passportParams = new URLSearchParams({
    from_session: sessionId,
    student_name: student.full_name,
  });
  const passportHref = `/coach/students/${encodeURIComponent(student.student_id)}/passport?${passportParams.toString()}`;
  const noteBody = noteText.trim();

  return (
    <li
      data-testid={`roster-${student.student_id}`}
      className="rounded-lg border bg-white p-3"
      style={{ borderColor: "var(--rally-line)" }}
    >
      <div className="flex flex-col gap-2 sm:flex-row sm:flex-wrap sm:items-center sm:justify-between">
        <div className="flex min-w-0 flex-1 flex-wrap items-center gap-1.5">
          <p className="text-sm font-medium" style={{ color: "var(--rally-ink)" }}>
            {student.full_name}
          </p>
          {student.expected_absence && <Chip variant="pending" label="EXPECTED ABSENCE" />}
          {student.entry_source === "makeup" && <Chip variant="makeup" label="MAKE-UP" />}
          {student.entry_source === "trial" && <Chip variant="waitlist" label="TRIAL" />}
          {queued && (
            <span
              data-testid={`mark-queued-${student.student_id}`}
              className="inline-flex items-center rounded-[3px] border border-amber-200 bg-amber-50 px-2 py-[3px] font-mono text-[10px] font-bold tracking-chip text-amber-800"
            >
              QUEUED
            </span>
          )}
        </div>
        <div className="flex flex-col gap-2 sm:flex-row sm:items-center">
          <div
            role="group"
            aria-label={`Attendance for ${student.full_name}`}
            className="flex gap-2"
          >
            {/* Present */}
            <button
              data-testid={`mark-${student.student_id}-present`}
              disabled={markDisabled}
              aria-pressed={marked === "present"}
              onClick={() => onMark("present")}
              className={MARK_BUTTON_BASE}
              style={
                marked === "present"
                  ? {
                      background: "#16a34a",
                      borderColor: "#16a34a",
                      color: "#fff",
                      fontWeight: 700,
                    }
                  : {
                      borderColor: "var(--rally-line)",
                      color: "var(--rally-muted)",
                    }
              }
            >
              {marked === "present" ? (
                <>
                  <span aria-hidden="true">✓ </span>Present
                </>
              ) : (
                "Present"
              )}
            </button>
            {/* Absent */}
            <button
              data-testid={`mark-${student.student_id}-absent`}
              disabled={markDisabled}
              aria-pressed={marked === "absent"}
              onClick={() => onMark("absent")}
              className={MARK_BUTTON_BASE}
              style={
                marked === "absent"
                  ? {
                      background: "#dc2626",
                      borderColor: "#dc2626",
                      color: "#fff",
                      fontWeight: 700,
                    }
                  : {
                      borderColor: "var(--rally-line)",
                      color: "var(--rally-muted)",
                    }
              }
            >
              {marked === "absent" ? (
                <>
                  <span aria-hidden="true">✕ </span>Absent
                </>
              ) : (
                "Absent"
              )}
            </button>
          </div>
          <div className="flex gap-2">
            <Link
              href={passportHref as Parameters<typeof Link>[0]["href"]}
              className={SECONDARY_BUTTON_BASE}
              style={{
                borderColor: "var(--rally-line)",
                color: "var(--rally-muted)",
              }}
            >
              Skills
            </Link>
            {/* Note toggle */}
            <button
              onClick={onToggleNote}
              aria-expanded={noteOpen}
              className={SECONDARY_BUTTON_BASE}
              style={
                noteOpen
                  ? {
                      background: "#facc15",
                      borderColor: "#facc15",
                      color: "#0a0f1c",
                    }
                  : {
                      borderColor: "var(--rally-line)",
                      color: "var(--rally-muted)",
                    }
              }
            >
              Note
            </button>
            {/* Billing preview toggle — online only (offline policy). */}
            {showBilling && (
              <button
                data-testid={`billing-toggle-${student.student_id}`}
                onClick={onToggleBilling}
                aria-expanded={billingOpen}
                disabled={!online}
                className={SECONDARY_BUTTON_BASE}
                style={{
                  borderColor: "var(--rally-line)",
                  color: "var(--rally-muted)",
                }}
              >
                Billing
              </button>
            )}
          </div>
        </div>
      </div>

      {local?.error && (
        <p
          data-testid={`mark-error-${student.student_id}`}
          className="mt-1.5 text-xs text-red-600"
        >
          {local.error}
          {local.needsReview && (
            <>
              {" "}
              <Link href="/coach/needs-review" className="font-semibold underline">
                Open Needs review
              </Link>
            </>
          )}
        </p>
      )}

      {/* Inline note box */}
      {noteOpen && (
        <div className="mt-3 space-y-2">
          <textarea
            value={noteText}
            onChange={(e) => onNoteChange(e.target.value)}
            rows={2}
            placeholder={`Progress note for ${student.full_name}…`}
            className="w-full rounded-md border px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-yellow-400"
            style={{
              borderColor: "var(--rally-line)",
              background: "var(--rally-paper)",
            }}
          />
          {assistant ? (
            <p
              data-testid="note-private-hint"
              className="text-xs"
              style={{ color: "var(--rally-muted)" }}
            >
              Notes you write stay private to coaches.
            </p>
          ) : (
            <label className="flex min-h-[44px] items-center gap-2 text-sm">
              <input
                type="checkbox"
                data-testid={`note-share-${student.student_id}`}
                checked={noteShare}
                onChange={(e) => onNoteShareChange(e.target.checked)}
                className="h-5 w-5 rounded border"
                style={{ accentColor: "#facc15" }}
              />
              <span style={{ color: "var(--rally-ink)" }}>Share with parent</span>
            </label>
          )}
          <div className="flex flex-wrap items-center gap-2">
            <button
              disabled={noteSaving || !noteBody || !online}
              onClick={() =>
                onNoteSave(noteBody, !assistant && noteShare ? "shared" : "private")
              }
              className="min-h-[44px] rounded-md px-4 py-1.5 text-sm font-semibold disabled:opacity-50"
              style={{ background: "#facc15", color: "#0a0f1c" }}
            >
              {noteSaving ? "Saving…" : "Save note"}
            </button>
            {!online && (
              <span className="text-xs" style={{ color: "var(--rally-muted)" }}>
                Reconnect to save notes.
              </span>
            )}
          </div>

          {notes.length > 0 && (
            <ul className="space-y-2 border-t pt-2" style={{ borderColor: "var(--rally-line)" }}>
              {notes.map((note) => {
                const shared = note.visibility === "shared";
                const pending = noteVisibilityPendingId === note.note_id;
                return (
                  <li
                    key={note.note_id}
                    data-testid={`note-${note.note_id}`}
                    className="rounded-md border p-2"
                    style={{ borderColor: "var(--rally-line)" }}
                  >
                    <p
                      className="whitespace-pre-wrap text-sm"
                      style={{ color: "var(--rally-ink)" }}
                    >
                      {note.body}
                    </p>
                    <div className="mt-1.5 flex flex-wrap items-center justify-between gap-2">
                      <span
                        data-testid={`note-visibility-${note.note_id}`}
                        className={`inline-flex items-center rounded-[3px] px-2 py-[3px] font-mono text-[10px] font-bold tracking-chip ${
                          shared
                            ? "bg-green-50 text-green-800"
                            : "bg-neutral-100 text-neutral-600"
                        }`}
                      >
                        {shared ? "SHARED WITH PARENT" : "PRIVATE"}
                      </span>
                      {!assistant && (
                        <button
                          data-testid={`note-share-toggle-${note.note_id}`}
                          disabled={pending || !online}
                          onClick={() =>
                            onNoteVisibility(note.note_id, shared ? "private" : "shared")
                          }
                          className="min-h-[44px] rounded-md border px-3 text-xs font-medium disabled:opacity-50"
                          style={{
                            borderColor: "var(--rally-line)",
                            color: "var(--rally-ink)",
                          }}
                        >
                          {pending ? "Saving…" : shared ? "Make private" : "Share"}
                        </button>
                      )}
                    </div>
                  </li>
                );
              })}
            </ul>
          )}
        </div>
      )}

      {showBilling && billingOpen && (
        <BillingPreviewDrawer
          sessionId={sessionId}
          studentId={student.student_id}
          studentName={student.full_name}
          onClose={onToggleBilling}
        />
      )}
    </li>
  );
}
