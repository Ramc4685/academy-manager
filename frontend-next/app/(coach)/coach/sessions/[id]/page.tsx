"use client";

import { use, useMemo, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { ulid } from "ulid";

import { getCoachToday, markAttendance, type AttendanceStatus, type CoachRosterEntry, type CoachSession } from "@/lib/api/coach";
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
    </section>
  );
}

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
