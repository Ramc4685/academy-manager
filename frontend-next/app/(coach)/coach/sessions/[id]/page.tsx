"use client";

import { use, useMemo, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { ulid } from "ulid";

import {
  createLessonPlan,
  createProgressNote,
  getCoachToday,
  listLessonPlans,
  listProgressNotes,
  markAttendance,
  type AttendanceStatus,
  type CoachRosterEntry,
  type CoachSession,
} from "@/lib/api/coach";
import { queryKeys } from "@/lib/query/keys";
import { useOnline } from "@/lib/pwa/online";
import { enqueue } from "@/lib/offline/queue";
import { syncNow } from "@/lib/offline/sync";

const OFFLINE_WRITES_ENABLED = process.env.NEXT_PUBLIC_W1B_OFFLINE_WRITES === "1";

function todayISO(): string {
  return new Date().toISOString().slice(0, 10);
}

interface PageProps {
  params: Promise<{ id: string }>;
}

interface OptimisticEntry {
  student_id: string;
  status: AttendanceStatus | null; // null = unmarked
  pending: boolean;
  error?: { code: string; message: string };
}

export default function SessionDetailPage({ params }: PageProps) {
  const { id } = use(params);
  const queryClient = useQueryClient();
  const online = useOnline();
  const date = todayISO();

  const { data: today, isLoading } = useQuery({
    queryKey: queryKeys.coach.today(date),
    queryFn: () => getCoachToday(date),
    staleTime: 5 * 60 * 1000,
  });

  const session: CoachSession | undefined = useMemo(
    () => today?.sessions.find((s) => s.session_id === id),
    [today, id]
  );

  const [localMarks, setLocalMarks] = useState<Record<string, OptimisticEntry>>({});
  const [lessonTitle, setLessonTitle] = useState("");
  const [lessonBody, setLessonBody] = useState("");
  const [noteStudentId, setNoteStudentId] = useState("");
  const [noteBody, setNoteBody] = useState("");

  const lessonPlans = useQuery({
    queryKey: ["coach", "lesson-plans", id],
    queryFn: () => listLessonPlans(id),
    enabled: Boolean(session),
  });
  const progressNotes = useQuery({
    queryKey: ["coach", "progress-notes", id],
    queryFn: () => listProgressNotes(id),
    enabled: Boolean(session),
  });

  const lessonMutation = useMutation({
    mutationFn: () => createLessonPlan(id, { title: lessonTitle, body: lessonBody }),
    onSuccess: () => {
      setLessonTitle("");
      setLessonBody("");
      void queryClient.invalidateQueries({ queryKey: ["coach", "lesson-plans", id] });
    },
  });
  const noteMutation = useMutation({
    mutationFn: () => createProgressNote(id, { student_id: noteStudentId, body: noteBody }),
    onSuccess: () => {
      setNoteBody("");
      void queryClient.invalidateQueries({ queryKey: ["coach", "progress-notes", id] });
    },
  });

  const mutation = useMutation({
    mutationFn: async (vars: { student_id: string; status: AttendanceStatus }) => {
      const payload = {
        mutation_id: ulid(),
        session_id: id,
        student_id: vars.student_id,
        status: vars.status,
        client_app_version: "v2-w1b",
        marked_at_client: new Date().toISOString(),
      };
      if (online) {
        return markAttendance(payload);
      }
      if (!OFFLINE_WRITES_ENABLED) {
        // Wave 1A behavior preserved when the W1B flag is off.
        throw Object.assign(new Error("Offline writes disabled"), {
          status: 0,
          code: "OfflineWritesDisabled",
        });
      }
      await enqueue({ mutation_id: payload.mutation_id, endpoint: "/coach/attendance", payload });
      // Schedule a sync attempt; if we come back online before it fires,
      // the auto-sync online listener will catch it.
      void syncNow();
      return {
        attendance_id: payload.mutation_id,
        session_id: payload.session_id,
        student_id: payload.student_id,
        status: payload.status,
        marked_at: payload.marked_at_client,
      };
    },
    onMutate: ({ student_id, status }) => {
      setLocalMarks((m) => ({
        ...m,
        [student_id]: { student_id, status, pending: true },
      }));
    },
    onSuccess: (res) => {
      setLocalMarks((m) => ({
        ...m,
        [res.student_id]: { student_id: res.student_id, status: res.status, pending: false },
      }));
      // Force refetch to keep cache fresh on next visit.
      void queryClient.invalidateQueries({ queryKey: queryKeys.coach.today(date) });
    },
    onError: (err: unknown, vars) => {
      const code = (err as { code?: string }).code ?? "Unknown";
      const message = (err as { message?: string }).message ?? "Failed";
      setLocalMarks((m) => ({
        ...m,
        [vars.student_id]: {
          student_id: vars.student_id,
          status: null,
          pending: false,
          error: { code, message },
        },
      }));
    },
  });

  if (isLoading) {
    return <div className="text-neutral-500">Loading session…</div>;
  }

  if (!session) {
    return (
      <div className="rounded-md border border-amber-200 bg-amber-50 p-4 text-sm text-amber-800 dark:border-amber-900 dark:bg-amber-950 dark:text-amber-100">
        Session not found for today. Pull to refresh or go back to{" "}
        <a className="underline" href="/coach/today">
          Today
        </a>
        .
      </div>
    );
  }

  return (
    <section data-testid="session-detail">
      <header className="mb-4">
        <h1 className="text-xl font-semibold">{session.title}</h1>
        <p className="text-sm text-neutral-500">{session.location}</p>
      </header>

      {!online && (
        <p
          data-testid={OFFLINE_WRITES_ENABLED ? "offline-queueing" : "offline-write-blocked"}
          className="mb-4 rounded-md border border-amber-200 bg-amber-50 p-3 text-sm text-amber-800 dark:border-amber-900 dark:bg-amber-950 dark:text-amber-100"
        >
          {OFFLINE_WRITES_ENABLED
            ? "You're offline — marks will sync when you reconnect."
            : "You're offline — reconnect to mark attendance."}
        </p>
      )}

      <ul className="space-y-2" data-testid="roster">
        {session.roster.map((student) => (
          <RosterRow
            key={student.student_id}
            student={student}
            local={localMarks[student.student_id]}
            disabled={!online}
            onMark={(status) =>
              mutation.mutate({ student_id: student.student_id, status })
            }
          />
        ))}
      </ul>

      <div className="mt-8 grid gap-6 lg:grid-cols-2">
        <section className="rounded-lg border border-neutral-200 p-4 dark:border-neutral-800">
          <h2 className="text-lg font-semibold">Lesson plan</h2>
          <form
            className="mt-3 space-y-3"
            onSubmit={(event) => {
              event.preventDefault();
              lessonMutation.mutate();
            }}
          >
            <input
              value={lessonTitle}
              onChange={(event) => setLessonTitle(event.target.value)}
              required
              className={inputClass}
              placeholder="Focus for this session"
            />
            <textarea
              value={lessonBody}
              onChange={(event) => setLessonBody(event.target.value)}
              required
              className={inputClass}
              rows={4}
              placeholder="Drills, rotations, and coaching notes"
            />
            <button
              type="submit"
              disabled={lessonMutation.isPending}
              className="min-h-touch rounded-md bg-blue-600 px-4 text-sm font-medium text-white hover:bg-blue-700 disabled:opacity-60"
            >
              {lessonMutation.isPending ? "Saving..." : "Save plan"}
            </button>
          </form>
          <ul className="mt-4 space-y-2">
            {(lessonPlans.data?.plans ?? []).map((plan) => (
              <li key={plan.lesson_plan_id} className="rounded-md bg-neutral-50 p-3 text-sm dark:bg-neutral-900">
                <p className="font-medium">{plan.title}</p>
                <p className="mt-1 text-neutral-600 dark:text-neutral-300">{plan.body}</p>
              </li>
            ))}
          </ul>
        </section>

        <section className="rounded-lg border border-neutral-200 p-4 dark:border-neutral-800">
          <h2 className="text-lg font-semibold">Progress note</h2>
          <form
            className="mt-3 space-y-3"
            onSubmit={(event) => {
              event.preventDefault();
              noteMutation.mutate();
            }}
          >
            <select
              value={noteStudentId}
              onChange={(event) => setNoteStudentId(event.target.value)}
              required
              className={inputClass}
            >
              <option value="">Select student</option>
              {session.roster.map((student) => (
                <option key={student.student_id} value={student.student_id}>
                  {student.full_name}
                </option>
              ))}
            </select>
            <textarea
              value={noteBody}
              onChange={(event) => setNoteBody(event.target.value)}
              required
              className={inputClass}
              rows={4}
              placeholder="What changed for this student today"
            />
            <button
              type="submit"
              disabled={noteMutation.isPending}
              className="min-h-touch rounded-md bg-blue-600 px-4 text-sm font-medium text-white hover:bg-blue-700 disabled:opacity-60"
            >
              {noteMutation.isPending ? "Saving..." : "Save note"}
            </button>
          </form>
          <ul className="mt-4 space-y-2">
            {(progressNotes.data?.notes ?? []).map((note) => {
              const student = session.roster.find((row) => row.student_id === note.student_id);
              return (
                <li key={note.note_id} className="rounded-md bg-neutral-50 p-3 text-sm dark:bg-neutral-900">
                  <p className="font-medium">{student?.full_name ?? note.student_id}</p>
                  <p className="mt-1 text-neutral-600 dark:text-neutral-300">{note.body}</p>
                </li>
              );
            })}
          </ul>
        </section>
      </div>
    </section>
  );
}

const inputClass =
  "w-full rounded-md border border-neutral-300 bg-white px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500 dark:border-neutral-700 dark:bg-neutral-900";

function RosterRow({
  student,
  local,
  disabled,
  onMark,
}: {
  student: CoachRosterEntry;
  local?: OptimisticEntry;
  disabled: boolean;
  onMark: (status: AttendanceStatus) => void;
}) {
  return (
    <li
      data-testid={`roster-${student.student_id}`}
      className="rounded-lg border border-neutral-200 p-3 dark:border-neutral-800"
    >
      <div className="flex items-center justify-between gap-3">
        <p className="font-medium">{student.full_name}</p>
        <div className="flex gap-1" role="group" aria-label={`Mark attendance for ${student.full_name}`}>
          {(["present", "late", "absent"] as const).map((s) => (
            <button
              key={s}
              data-testid={`mark-${student.student_id}-${s}`}
              disabled={disabled || local?.pending}
              onClick={() => onMark(s)}
              className={`min-h-touch min-w-touch rounded-md border px-3 text-sm capitalize disabled:opacity-50 ${
                local?.status === s
                  ? "border-blue-500 bg-blue-500 text-white"
                  : "border-neutral-300 dark:border-neutral-700"
              }`}
            >
              {s}
            </button>
          ))}
        </div>
      </div>
      {local?.error && (
        <p data-testid={`mark-error-${student.student_id}`} className="mt-2 text-xs text-red-600">
          {local.error.code}: {local.error.message}
        </p>
      )}
    </li>
  );
}
