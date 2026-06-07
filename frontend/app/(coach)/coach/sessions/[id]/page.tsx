"use client";

import Link from "next/link";
import { use, useMemo, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { ulid } from "ulid";

import {
  createProgressNote,
  getCoachToday,
  markAttendance,
  type AttendanceStatus,
  type CoachRosterEntry,
} from "@/lib/api/coach";
import { queryKeys } from "@/lib/query/keys";
import { useOnline } from "@/lib/pwa/online";
import { formatSessionTimeRange } from "@/lib/time/session-time";

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
}

function formatApiError(err: unknown): string {
  const apiError = err as { code?: string; message?: string };
  const message = apiError.message ?? "Failed";
  return apiError.code ? `${apiError.code}: ${message}` : message;
}

export default function SessionDetailPage({ params, searchParams }: PageProps) {
  const { id } = use(params);
  const { date: dateParam } = use(searchParams);
  const decodedId = decodeURIComponent(id);
  const queryClient = useQueryClient();
  const online = useOnline();

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

  const [localMarks, setLocalMarks] = useState<Record<string, OptimisticEntry>>(
    {},
  );
  // noteOpen tracks which student has the inline note box open
  const [noteOpen, setNoteOpen] = useState<string | null>(null);
  const [noteTexts, setNoteTexts] = useState<Record<string, string>>({});

  const noteMutation = useMutation({
    mutationFn: ({ studentId, body }: { studentId: string; body: string }) =>
      createProgressNote(session?.session_id ?? decodedId, {
        student_id: studentId,
        body,
      }),
    onSuccess: (_data, { studentId }) => {
      setNoteTexts((t) => ({ ...t, [studentId]: "" }));
      setNoteOpen(null);
      void queryClient.invalidateQueries({
        queryKey: ["coach", "progress-notes", id],
      });
    },
  });

  const attendanceMutation = useMutation({
    mutationFn: async (vars: {
      student_id: string;
      status: AttendanceStatus;
    }) =>
      markAttendance({
        mutation_id: ulid(),
        occurrence_id: session?.occurrence_id ?? decodedId,
        session_id: session?.session_id ?? decodedId,
        student_id: vars.student_id,
        status: vars.status,
        client_app_version: "v2-w1b",
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
    },
  });

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

  const progressHref = `/coach/sessions/${encodeURIComponent(session.session_id)}/progress`;

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
        </div>
        <Link
          href={progressHref as Parameters<typeof Link>[0]["href"]}
          className="inline-flex min-h-9 items-center justify-center rounded-md bg-blue-600 px-3 py-2 text-sm font-semibold text-white transition-colors hover:bg-blue-700"
        >
          Skill Progress
        </Link>
      </header>

      {!online && (
        <p className="mb-4 rounded-md border border-amber-200 bg-amber-50 p-3 text-sm text-amber-800">
          You&apos;re offline — reconnect to mark attendance.
        </p>
      )}

      {/* Attendance roster */}
      <section>
        <h2
          className="mb-2 text-sm font-semibold uppercase tracking-wide"
          style={{ color: "var(--rally-muted)" }}
        >
          Attendance · {roster.length} students
        </h2>
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
                noteOpen={noteOpen === student.student_id}
                noteText={noteTexts[student.student_id] ?? ""}
                disabled={!online}
                onMark={(status) =>
                  attendanceMutation.mutate({
                    student_id: student.student_id,
                    status,
                  })
                }
                onToggleNote={() =>
                  setNoteOpen((prev) =>
                    prev === student.student_id ? null : student.student_id,
                  )
                }
                onNoteChange={(text) =>
                  setNoteTexts((t) => ({ ...t, [student.student_id]: text }))
                }
                onNoteSave={(body) =>
                  noteMutation.mutate({ studentId: student.student_id, body })
                }
                noteSaving={noteMutation.isPending}
              />
            ))}
          </ul>
        )}
      </section>
    </section>
  );
}

function RosterRow({
  student,
  sessionId,
  local,
  noteOpen,
  noteText,
  disabled,
  onMark,
  onToggleNote,
  onNoteChange,
  onNoteSave,
  noteSaving,
}: {
  student: CoachRosterEntry;
  sessionId: string;
  local?: OptimisticEntry;
  noteOpen: boolean;
  noteText: string;
  disabled: boolean;
  onMark: (status: AttendanceStatus) => void;
  onToggleNote: () => void;
  onNoteChange: (text: string) => void;
  onNoteSave: (body: string) => void;
  noteSaving: boolean;
}) {
  const marked = local?.status;
  const passportHref = `/coach/students/${encodeURIComponent(student.student_id)}/passport?from_session=${encodeURIComponent(sessionId)}`;

  return (
    <li
      data-testid={`roster-${student.student_id}`}
      className="rounded-lg border bg-white p-3"
      style={{ borderColor: "var(--rally-line)" }}
    >
      <div className="flex items-center justify-between gap-2">
        <p
          className="min-w-0 flex-1 text-sm font-medium"
          style={{ color: "var(--rally-ink)" }}
        >
          {student.full_name}
        </p>
        <div className="flex shrink-0 flex-wrap justify-end gap-1" role="group">
          <Link
            href={passportHref as Parameters<typeof Link>[0]["href"]}
            className="rounded-md border px-2.5 py-1 text-xs font-medium transition-colors"
            style={{
              borderColor: "var(--rally-line)",
              color: "var(--rally-muted)",
            }}
          >
            Skills
          </Link>
          {/* Present */}
          <button
            data-testid={`mark-${student.student_id}-present`}
            disabled={disabled || local?.pending}
            onClick={() => onMark("present")}
            className="rounded-md border px-2.5 py-1 text-xs font-medium transition-colors disabled:opacity-50"
            style={
              marked === "present"
                ? {
                    background: "#16a34a",
                    borderColor: "#16a34a",
                    color: "#fff",
                  }
                : {
                    borderColor: "var(--rally-line)",
                    color: "var(--rally-muted)",
                  }
            }
          >
            Present
          </button>
          {/* Absent */}
          <button
            data-testid={`mark-${student.student_id}-absent`}
            disabled={disabled || local?.pending}
            onClick={() => onMark("absent")}
            className="rounded-md border px-2.5 py-1 text-xs font-medium transition-colors disabled:opacity-50"
            style={
              marked === "absent"
                ? {
                    background: "#dc2626",
                    borderColor: "#dc2626",
                    color: "#fff",
                  }
                : {
                    borderColor: "var(--rally-line)",
                    color: "var(--rally-muted)",
                  }
            }
          >
            Absent
          </button>
          {/* Note toggle */}
          <button
            onClick={onToggleNote}
            className="rounded-md border px-2.5 py-1 text-xs font-medium transition-colors"
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

      {local?.error && (
        <p
          data-testid={`mark-error-${student.student_id}`}
          className="mt-1.5 text-xs text-red-600"
        >
          {local.error}
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
          <button
            disabled={noteSaving || !noteText.trim()}
            onClick={() => onNoteSave(noteText.trim())}
            className="rounded-md px-3 py-1.5 text-xs font-semibold disabled:opacity-50"
            style={{ background: "#facc15", color: "#0a0f1c" }}
          >
            {noteSaving ? "Saving…" : "Save note — parent will see this"}
          </button>
        </div>
      )}
    </li>
  );
}
