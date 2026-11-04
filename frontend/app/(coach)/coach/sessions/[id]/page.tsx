"use client";

import Link from "next/link";
import { use, useCallback, useEffect, useMemo, useRef, useState } from "react";
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
import { useIsAssistantCoach } from "@/components/coach/coach-surface-context";
import { SessionDetailTabs } from "@/components/coach/SessionDetailTabs";
import { TrialOutcomeControl } from "@/components/coach/trial-outcome-control";
import { Chip } from "@/components/ds/chip";
import { formatCents } from "@/lib/money";
import { queueMark, queuedMarksFor, type QueuedMark } from "@/lib/offline/attendance-queue";
import { isBulkMarkEligible } from "@/lib/coach/bulk-eligibility";
import { BulkMarkUndoWindow } from "@/lib/coach/bulk-mark-undo";
import { markProgress } from "@/lib/coach/marking";
import { onSync, syncNow } from "@/lib/offline/sync";
import { lifecycleLabel } from "@/lib/format/lifecycle-copy";
import { queryKeys } from "@/lib/query/keys";
import { useOnline } from "@/lib/pwa/online";
import { formatSessionTimeRange } from "@/lib/time/session-time";

import { formatBulkAttendanceError } from "./bulk-attendance-error";

const CLIENT_APP_VERSION = "v2-w1b";

const NO_STUDENTS: ReadonlySet<string> = new Set();

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
    "This student isn't actively enrolled in this session and has no approved make-up or trial for today, so attendance can't be saved. Ask the admin to check their roster status.",
  "Coaching.BulkStudentNotEnrolled":
    "Nothing was saved: someone on this roster isn't eligible for attendance today. Refresh the roster and mark the class again.",
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
  const { data: today, isLoading, isError, dataUpdatedAt } = useQuery({
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
  // #846: "Mark rest present" is HELD on this phone for a few seconds before
  // anything is sent. These are the students in the held batch — their rows
  // show a pending style and the bottom bar offers Undo. Undo inside the
  // window means nothing was ever sent: no notification, no billing sync.
  const [pendingBulkIds, setPendingBulkIds] = useState<readonly string[]>([]);
  const pendingBulkSet = useMemo(() => new Set(pendingBulkIds), [pendingBulkIds]);
  const undoWindowRef = useRef<BulkMarkUndoWindow | null>(null);
  const undoWindow = (): BulkMarkUndoWindow =>
    (undoWindowRef.current ??= new BulkMarkUndoWindow());
  // The commit closure must see the CURRENT connectivity and roster: the
  // coach can walk out of signal during the window, and the batch has to go
  // to whichever path is right when it actually leaves.
  const commitBulkRef = useRef<(studentIds: string[]) => void>(() => undefined);
  // Why the last "Mark all present" was refused as a whole (#672): the bulk
  // endpoint saves nothing when any row is ineligible, so name the rows.
  const [bulkError, setBulkError] = useState<string | null>(null);
  // The students that 422 named. Kept apart from the banner and from row
  // errors: the retry must leave exactly these rows out, and keep leaving
  // them out after the banner clears, until the roster is refetched
  // (`rosterVersion` is the query's dataUpdatedAt when the 422 landed) or a
  // single mark / correction for that student succeeds.
  const [bulkIneligible, setBulkIneligible] = useState<{
    ids: ReadonlySet<string>;
    rosterVersion: number;
  }>({ ids: NO_STUDENTS, rosterVersion: 0 });
  const ineligibleIds =
    bulkIneligible.rosterVersion === dataUpdatedAt ? bulkIneligible.ids : NO_STUDENTS;
  const clearIneligible = (student_id: string): void =>
    setBulkIneligible((prev) => {
      if (!prev.ids.has(student_id)) return prev;
      const ids = new Set(prev.ids);
      ids.delete(student_id);
      return { ...prev, ids };
    });
  // noteOpen tracks which student has the inline note box open
  const [noteOpen, setNoteOpen] = useState<string | null>(null);
  const [noteTexts, setNoteTexts] = useState<Record<string, string>>({});
  const [noteShare, setNoteShare] = useState<Record<string, boolean>>({});
  /**
   * #895: this is the marking screen. The announcements composer — a 3-row
   * textarea, an urgency checkbox and a Post button — sat open under the
   * roster on every visit, so the thing the coach actually came for competed
   * with a form most visits never use. It now opens on request. The shared
   * AnnouncementsPanel is untouched, so the admin session page still renders
   * the composer open, which is right for the surface it is on.
   */
  const [announcementsOpen, setAnnouncementsOpen] = useState(false);

  const progressNotesKey = queryKeys.coach.progressNotes(sessionId);
  const { data: notesData } = useQuery({
    queryKey: progressNotesKey,
    queryFn: () => listProgressNotes(sessionId),
    // Existing notes only render inside an open note box, so don't spend a
    // request on every session-detail load. The staleTime keeps re-opens free.
    enabled: online && Boolean(session) && noteOpen !== null,
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

  // Never lose a held batch (#846). Every exit that is not Undo sends it:
  // the phone locking or the app backgrounding (visibilitychange hidden on
  // Android/desktop, pagehide on iOS Safari — the two fire inconsistently,
  // so both are wired), and leaving the route, which unmounts this page and
  // runs the cleanup below.
  useEffect(() => {
    const flush = (): void => undoWindowRef.current?.flush();
    const onVisibility = (): void => {
      if (document.visibilityState === "hidden") flush();
    };
    window.addEventListener("pagehide", flush);
    document.addEventListener("visibilitychange", onVisibility);
    return () => {
      window.removeEventListener("pagehide", flush);
      document.removeEventListener("visibilitychange", onVisibility);
      flush();
    };
  }, []);

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
        // No invalidation here: replaying N marks would fire N refetches that
        // cancel each other. The `finished` branch above refetches once, and
        // the local state already shows the mark as saved.
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
      clearIneligible(res.student_id);
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
      clearIneligible(res.student_id);
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
      setBulkError(null);
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
      // 422 = the server refused the whole batch because some rows are not
      // eligible today (#672). Name them, flag their rows, and leave the
      // other rows unmarked (nothing was saved) so the coach can retry
      // without the named students.
      const rejection = formatBulkAttendanceError(err, roster);
      if (rejection) {
        const ineligible = new Set(rejection.ineligibleIds);
        setBulkError(rejection.message);
        setBulkIneligible({ ids: ineligible, rosterVersion: dataUpdatedAt });
        setLocalMarks((m) => {
          const next = { ...m };
          for (const student_id of studentIds) {
            if (ineligible.has(student_id)) {
              next[student_id] = {
                student_id,
                status: null,
                pending: false,
                error: ATTENDANCE_ERROR_MESSAGES["Coaching.StudentNotEnrolled"],
              };
            } else {
              delete next[student_id];
            }
          }
          return next;
        });
        return;
      }
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
      (student) =>
        !hasServerMark(student) &&
        !queuedMarks[student.student_id] &&
        // Already inside a held "Mark rest present" batch (#846): the bar
        // owns them until the window closes, so a second batch can never
        // cover the same student.
        !pendingBulkSet.has(student.student_id) &&
        // Named ineligible by the last bulk attempt (#672): leave them out
        // of the retry; the row keeps its own explanation. Other rows' own
        // errors (a failed single tap) never shrink the retry.
        !ineligibleIds.has(student.student_id) &&
        // #866: and the two lifecycle facts the roster already shows — an
        // ON HOLD seat, a parent's absence notice — so the count stops
        // promising a number the server would refuse (or a parent already
        // withdrew). The line above stays the authority for everything this
        // cannot predict; nothing about the save path changes.
        isBulkMarkEligible(student),
    )
    .map((student) => student.student_id);
  const queuedCount = Object.keys(queuedMarks).length;
  const anySavedMark = roster.some(hasServerMark);
  // Issue #777: "am I done marking" needs a fraction, not a student count.
  // Marks made on this phone (optimistic or queued offline) count too, so the
  // header keeps up with the coach's own thumb.
  const progress = markProgress(
    roster,
    new Set([
      ...roster.filter(hasServerMark).map((student) => student.student_id),
      ...Object.keys(queuedMarks),
    ]),
  );

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
        // #841: the roster and the class title are on screen right now; the
        // Needs-review tray has no way to look them up later, so capture them.
        student_full_name: roster.find((s) => s.student_id === student_id)?.full_name,
        session_title: session?.title,
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

  /**
   * Send a held batch for real. Unchanged from what the tap used to do
   * directly (#846 only moved it behind the undo window): the bulk endpoint
   * online, one queued mark per student offline — same payloads, same
   * idempotency keys, same #841 labels.
   */
  function commitBulkMark(studentIds: string[]): void {
    setPendingBulkIds([]);
    if (online) {
      bulkAttendanceMutation.mutate(studentIds);
      return;
    }
    setQueueingAll(true);
    void (async () => {
      try {
        for (const student_id of studentIds) {
          await queueLocally(student_id, "present");
        }
      } finally {
        setQueueingAll(false);
      }
    })();
  }
  // Re-pointed after every render, so a batch that leaves late still uses
  // the latest connectivity and roster. No dependency array on purpose.
  useEffect(() => {
    commitBulkRef.current = commitBulkMark;
  });

  function handleMarkAll(): void {
    const batch = unmarkedStudentIds;
    if (batch.length === 0) return;
    setBulkError(null);
    setPendingBulkIds(batch);
    undoWindow().schedule(batch, (ids) => commitBulkRef.current(ids));
  }

  function handleUndoMarkAll(): void {
    // cancel() returns nothing once the batch has gone out, so a tap a beat
    // too late is a no-op rather than a half-undone class.
    undoWindow().cancel();
    setPendingBulkIds([]);
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
              Attendance · <span data-testid="marked-count">{progress.label}</span>
            </h2>
            {!progress.complete && (
              <span
                data-testid="needs-marks-badge"
                className="rounded-full border border-amber-300 bg-amber-50 px-2 py-0.5 text-xs font-semibold text-amber-800"
              >
                Needs marks
              </span>
            )}
            {queuedCount > 0 && (
              <span
                data-testid="queued-count"
                className="rounded-full border border-amber-200 bg-amber-50 px-2 py-0.5 text-xs font-semibold text-amber-800"
              >
                {queuedCount} queued
              </span>
            )}
          </div>
        </div>
        {bulkError && (
          <p
            data-testid="bulk-attendance-error"
            role="alert"
            className="mb-2 rounded-md border border-red-200 bg-red-50 px-3 py-2 text-xs text-red-700"
          >
            {bulkError}
          </p>
        )}
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
                pendingPresent={pendingBulkSet.has(student.student_id)}
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
                noteVisibilityFailed={noteVisibilityMutation.isError}
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
          <h2 className="mb-2">
            <button
              type="button"
              data-testid="announcements-toggle"
              aria-expanded={announcementsOpen}
              aria-controls="coach-session-announcements"
              onClick={() => setAnnouncementsOpen((open) => !open)}
              className="min-h-touch w-full rounded-lg border px-3 text-left text-sm font-semibold uppercase tracking-wide"
              style={{
                color: "var(--rally-muted)",
                borderColor: "var(--rally-line)",
              }}
            >
              Announcements
              <span aria-hidden="true" className="float-right font-normal">
                {announcementsOpen ? "−" : "+"}
              </span>
            </button>
          </h2>
          {announcementsOpen && (
            <div id="coach-session-announcements">
              <AnnouncementsPanel
                persona="coach"
                sessionId={session.session_id}
              />
            </div>
          )}
        </section>
      )}

      {/*
        #846: the batch action lives in the thumb arc, not in the top-right
        corner a coach has to shift grip to reach, and it is the same place
        the Undo answer appears — a coach who mis-taps looks where their
        thumb already is. Pinned above the shell's bottom nav; the spacer
        below keeps it off the last roster row.
      */}
      {roster.length > 0 && (
        <>
          <div aria-hidden="true" className="h-20" />
          <div
            className="fixed inset-x-0 z-20 px-4"
            style={{
              bottom:
                "calc(var(--coach-bottom-nav-height, 0px) + env(safe-area-inset-bottom, 0px) + 0.5rem)",
            }}
          >
            <div
              data-testid="mark-all-bar"
              className="mx-auto w-full max-w-md rounded-lg border p-2 shadow-lg"
              style={{
                background: "var(--rally-paper)",
                borderColor: "var(--rally-line)",
              }}
            >
              {pendingBulkIds.length > 0 ? (
                <div
                  data-testid="mark-all-undo-bar"
                  role="status"
                  className="flex items-center gap-2"
                >
                  <p
                    className="min-w-0 flex-1 px-1 text-sm font-semibold"
                    style={{ color: "var(--rally-ink)" }}
                  >
                    Marked {pendingBulkIds.length} present
                  </p>
                  <button
                    data-testid="mark-all-undo"
                    onClick={handleUndoMarkAll}
                    className="min-h-[44px] shrink-0 rounded-md border-2 px-5 text-sm font-bold transition-colors"
                    style={{
                      borderColor: "var(--rally-ink)",
                      color: "var(--rally-ink)",
                    }}
                  >
                    Undo
                  </button>
                </div>
              ) : (
                <button
                  data-testid="mark-all-present"
                  disabled={markAllPending || unmarkedStudentIds.length === 0}
                  onClick={handleMarkAll}
                  className="min-h-[44px] w-full rounded-md bg-status-green-800 px-4 text-sm font-semibold text-white transition-colors hover:opacity-90 disabled:opacity-50"
                >
                  {markAllPending
                    ? "Marking…"
                    : unmarkedStudentIds.length === 0
                      ? "All marked"
                      : `Mark rest present (${unmarkedStudentIds.length})`}
                </button>
              )}
            </div>
          </div>
        </>
      )}
    </section>
  );
}

// border-2, not border: the 1px --rally-line hairline disappeared in outdoor
// glare, which is exactly where coaches mark attendance (#844).
const MARK_BUTTON_BASE =
  "min-h-[44px] min-w-[44px] flex-1 rounded-md border-2 px-2 text-sm font-medium transition-colors disabled:opacity-50 sm:min-w-[88px]";
// #846: the secondary pair no longer claims a row of its own. They keep 44px
// targets but stop competing with Present/Absent for width.
const SECONDARY_BUTTON_BASE =
  "inline-flex min-h-[44px] min-w-[44px] shrink-0 items-center justify-center rounded-md border px-2 text-xs font-medium transition-colors disabled:opacity-50";

/**
 * The single lifecycle chip a roster row may show, or null.
 *
 * Order is precedence, not preference: an ending enrollment is the fact the
 * coach has to act on (say goodbye, stop expecting them), a hold is the
 * second, and a row that is simply active needs no chip at all — a roster
 * where every name carries a badge is a roster where none of them is read.
 */
function lifecycleChip(
  student: CoachRosterEntry,
): { variant: "closing" | "pending"; label: string } | null {
  if (student.pending_cancellation_at) {
    const day = new Date(student.pending_cancellation_at);
    const label = Number.isNaN(day.getTime())
      ? "ENDING"
      : `ENDS ${day.toLocaleDateString("en-US", { month: "short", day: "numeric" })}`;
    return { variant: "closing", label };
  }
  if (student.enrollment_status === "held" || student.enrollment_status === "reclaim_pending") {
    return {
      variant: "pending",
      label: lifecycleLabel("on_hold", student.hold_return_on),
    };
  }
  return null;
}

function RosterRow({
  student,
  sessionId,
  local,
  queued,
  pendingPresent,
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
  noteVisibilityFailed,
}: {
  student: CoachRosterEntry;
  sessionId: string;
  local?: OptimisticEntry;
  queued?: QueuedMark;
  /** In a held "Mark rest present" batch: shown as pending, not as saved (#846). */
  pendingPresent: boolean;
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
  /** The last visibility change failed — the chip silently reverted, so say so. */
  noteVisibilityFailed: boolean;
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
  // A row in a held batch is frozen until the window closes: the one control
  // that applies to it is Undo, in the bar (#846).
  const markDisabled =
    Boolean(local?.pending) || pendingPresent || (!online && savedOnServer);
  const passportParams = new URLSearchParams({
    from_session: sessionId,
    student_name: student.full_name,
  });
  const passportHref = `/coach/students/${encodeURIComponent(student.student_id)}/passport?${passportParams.toString()}`;
  const noteBody = noteText.trim();

  return (
    <li
      data-testid={`roster-${student.student_id}`}
      data-mark-pending={pendingPresent ? "true" : undefined}
      className="rounded-lg border bg-white px-3 py-2"
      style={{ borderColor: "var(--rally-line)" }}
    >
      {/*
        #846: name and tags own a line, the four controls share the next one.
        The old row stacked THREE blocks on a phone (~116px each, ~2,700px of
        scroll for a twelve-student class) and, on desktop, let the name wrap
        underneath the Present button.
      */}
      <div className="flex flex-col gap-1.5">
        <div className="flex min-w-0 flex-wrap items-center gap-1.5">
          <p className="text-sm font-medium" style={{ color: "var(--rally-ink)" }}>
            {student.full_name}
          </p>
          {student.expected_absence && <Chip variant="pending" label="EXPECTED ABSENCE" />}
          {student.entry_source === "makeup" && <Chip variant="makeup" label="MAKE-UP" />}
          {student.entry_source === "trial" && <Chip variant="waitlist" label="TRIAL" />}
          {/* Issue #773: at most ONE lifecycle chip per row. The coach already
              received enrollment_status and pending_cancellation_at and
              rendered neither, so a student whose last class is next week
              looked identical to one who just joined. */}
          {lifecycleChip(student) && (
            <Chip
              variant={lifecycleChip(student)!.variant}
              label={lifecycleChip(student)!.label}
            />
          )}
          {/* Issue #774: the ONE money fact a coach sees. The owner's decision
              (2026-09-12) replaced the per-row billing proration drawer with
              this, so a coach can say "there's a payment due" to the parent at
              the court and nothing more. Rendered only when something is
              actually overdue — never a "$0.00 due". */}
          {typeof student.payment_due_cents === "number" &&
            student.payment_due_cents > 0 && (
              <span data-testid={`payment-due-${student.student_id}`}>
                <Chip
                  variant="overdue"
                  label={`PAYMENT DUE ${formatCents(student.payment_due_cents)}`}
                />
              </span>
            )}
          {queued && (
            <span
              data-testid={`mark-queued-${student.student_id}`}
              className="inline-flex items-center rounded-[3px] border border-amber-200 bg-amber-50 px-2 py-[3px] font-mono text-[10px] font-bold tracking-chip text-amber-800"
            >
              QUEUED
            </span>
          )}
        </div>
        <div className="flex items-center gap-2">
          <div
            role="group"
            aria-label={`Attendance for ${student.full_name}`}
            className="flex min-w-0 flex-1 gap-2"
          >
            {/* Present */}
            <button
              data-testid={`mark-${student.student_id}-present`}
              disabled={markDisabled}
              aria-pressed={marked === "present"}
              onClick={() => onMark("present")}
              className={MARK_BUTTON_BASE}
              style={
                pendingPresent
                  ? {
                      // Held, not saved (#846). Deliberately NOT the solid
                      // green of a recorded mark: a coach must be able to see
                      // at a glance that this one is still cancellable. Same
                      // #844 ink (7.8:1 on this tint), hollow and dashed.
                      background: "#ecfdf5",
                      borderColor: "#065f46",
                      borderStyle: "dashed",
                      color: "#065f46",
                      fontWeight: 700,
                    }
                  : marked === "present"
                    ? {
                        // status-green-800: 7.8:1 with white, where green-600 was 3.3:1.
                        background: "#065f46",
                        borderColor: "#065f46",
                        color: "#fff",
                        fontWeight: 700,
                      }
                    : {
                        borderColor: "var(--rally-muted)",
                        color: "var(--rally-muted)",
                      }
              }
            >
              {pendingPresent ? (
                <>
                  <span aria-hidden="true">✓ </span>Present
                  <span className="sr-only"> — not saved yet, undo below</span>
                </>
              ) : marked === "present" ? (
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
                      // red-600 on white is already 4.8:1 — left as shipped.
                      background: "#dc2626",
                      borderColor: "#dc2626",
                      color: "#fff",
                      fontWeight: 700,
                    }
                  : {
                      borderColor: "var(--rally-muted)",
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
          <div className="flex shrink-0 gap-1.5">
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
          </div>
        </div>
      </div>

      {/* People CRM L3a: close the trial (Came / Didn't come), separate from
          the attendance mark above. Only trial rows carry a request id. */}
      {student.entry_source === "trial" && student.trial_request_id && (
        <TrialOutcomeControl
          requestId={student.trial_request_id}
          studentName={student.full_name}
          outcome={student.trial_outcome}
        />
      )}

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
                className="h-5 w-5 rounded border accent-rally-volt-400"
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

          {noteVisibilityFailed && (
            <p data-testid="note-visibility-error" className="text-xs text-red-600">
              Couldn&apos;t change who sees that note. Try again.
            </p>
          )}
        </div>
      )}

    </li>
  );
}
