"use client";

import { useMemo, useState } from "react";
import Link from "next/link";
import { useSearchParams } from "next/navigation";
import { useQuery } from "@tanstack/react-query";
import { ExternalLink } from "lucide-react";

import {
  getCoachTodayPlan,
  type LevelTeachingGroup,
  type SessionTeachingPlan,
} from "@/lib/api/coach";
import { queryKeys } from "@/lib/query/keys";
import { reportVitals } from "@/lib/pwa/vitals";
import { formatSessionTimeRange } from "@/lib/time/session-time";
import { LessonCardView } from "@/components/teaching/lesson-card";
import { StudentFocusRow } from "@/components/teaching/student-focus-row";

function todayISO(): string {
  const d = new Date();
  const year = d.getFullYear();
  const month = String(d.getMonth() + 1).padStart(2, "0");
  const day = String(d.getDate()).padStart(2, "0");
  return `${year}-${month}-${day}`;
}

export default function CoachTeachingPlanPage() {
  const searchParams = useSearchParams();
  const [date, setDate] = useState<string>(
    () => searchParams.get("date") ?? todayISO(),
  );

  const { data, isLoading, isError, refetch, isFetching } = useQuery({
    queryKey: queryKeys.coach.todayPlan(date),
    queryFn: () => getCoachTodayPlan(date),
    staleTime: 5 * 60 * 1000,
  });
  const sessions = Array.isArray(data?.sessions) ? data.sessions : [];

  useMemo(() => reportVitals("coach.today.plan"), []);

  return (
    <section data-testid="coach-teaching-plan">
      <header className="mb-4 flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between">
        <div>
          <Link
            href="/coach/today"
            className="text-xs text-rally-base hover:underline"
          >
            ‹ Today
          </Link>
          <h1 className="text-2xl font-semibold">Teaching plan</h1>
          <p className="text-sm text-neutral-500">{date}</p>
        </div>
        <DatePicker date={date} onChange={setDate} />
      </header>

      {isLoading && <PlanSkeleton />}

      {isError && (
        <div
          role="alert"
          data-testid="plan-error"
          className="rounded-md border border-red-200 bg-red-50 p-4 text-sm text-red-800 dark:border-red-900 dark:bg-red-950 dark:text-red-200"
        >
          <p>Couldn&apos;t load the teaching plan.</p>
          <button
            onClick={() => void refetch()}
            className="mt-2 min-h-touch rounded-md border px-3"
          >
            Retry
          </button>
        </div>
      )}

      {!isError && data && !data.pathway_configured && (
        <div
          data-testid="pathway-not-configured"
          role="status"
          className="mb-4 rounded-md border border-amber-200 bg-amber-50 p-4 text-sm text-amber-800 dark:border-amber-900 dark:bg-amber-950 dark:text-amber-200"
        >
          No skill pathway is configured for this program yet, so per-student
          guidance isn&apos;t available. Ask an admin to set up the pathway.
        </div>
      )}

      {!isError && data && sessions.length === 0 && (
        <p className="text-neutral-500" data-testid="plan-empty-state">
          No sessions today.
        </p>
      )}

      <div className="space-y-6">
        {sessions.map((s) => (
          <SessionPlan
            key={s.session_id}
            session={s}
            programId={data?.program_id ?? ""}
            date={date}
          />
        ))}
      </div>

      {isFetching && !isLoading && (
        <p className="mt-3 text-xs text-neutral-400">Refreshing…</p>
      )}
    </section>
  );
}

function SessionPlan({
  session,
  programId,
  date,
}: {
  session: SessionTeachingPlan;
  programId: string;
  date: string;
}) {
  const timeRange =
    session.start_at && session.end_at
      ? formatSessionTimeRange(session.start_at, session.end_at, session.timezone)
      : "";

  return (
    <section data-testid={`plan-session-${session.session_id}`}>
      <header className="mb-2 flex flex-col gap-1 sm:flex-row sm:items-baseline sm:justify-between">
        <div className="min-w-0">
          <h2 className="text-lg font-semibold">
            {session.title || "Session"}
          </h2>
          {session.location && (
            <p className="text-sm text-neutral-500">{session.location}</p>
          )}
        </div>
        {timeRange && (
          <p className="shrink-0 text-sm tabular-nums text-neutral-600 dark:text-neutral-300">
            {timeRange}
          </p>
        )}
      </header>

      {session.groups.length === 0 && session.unplaced.length === 0 && (
        <p className="text-sm text-neutral-500">No students on this roster.</p>
      )}

      <div className="space-y-4">
        {session.groups.map((group) => (
          <LevelSection
            key={group.level_id}
            group={group}
            programId={programId}
            sessionId={session.session_id}
            date={date}
          />
        ))}
      </div>

      {session.unplaced.length > 0 && (
        <div className="mt-4 rounded-xl border border-dashed border-neutral-300 p-4 dark:border-neutral-700">
          <p className="mb-2 text-sm font-semibold text-neutral-600">
            Not placed in a level
          </p>
          <ul className="space-y-1 text-sm text-neutral-600 dark:text-neutral-300">
            {session.unplaced.map((u) => (
              <li key={u.student_id}>{u.student_name}</li>
            ))}
          </ul>
        </div>
      )}
    </section>
  );
}

function LevelSection({
  group,
  programId,
  sessionId,
  date,
}: {
  group: LevelTeachingGroup;
  programId: string;
  sessionId: string;
  date: string;
}) {
  return (
    <section
      data-testid={`plan-level-${group.level_sequence}`}
      className="space-y-3"
    >
      <h3 className="text-sm font-semibold text-rally-base">
        Level {group.level_sequence} · {group.level_name}
      </h3>

      {group.lesson_card ? (
        <LessonCardView
          card={group.lesson_card}
          levelYoutubeLinks={group.youtube_links}
        />
      ) : (
        group.youtube_links.length > 0 && (
          <div className="flex flex-wrap gap-2">
            {group.youtube_links.map((link, i) => (
              <a
                key={link.url}
                href={link.url}
                target="_blank"
                rel="noopener noreferrer"
                data-testid={`plan-level-youtube-${group.level_sequence}-${i}`}
                className="inline-flex min-h-touch items-center gap-1.5 rounded-lg border border-red-200 bg-red-50 px-3 text-xs font-medium text-red-700 hover:bg-red-100 dark:border-red-900 dark:bg-red-950 dark:text-red-300"
              >
                <ExternalLink className="size-3.5" aria-hidden="true" />
                {link.title || "Watch video"}
              </a>
            ))}
          </div>
        )
      )}

      {group.students.length > 0 && (
        <ul className="space-y-2">
          {group.students.map((student) => (
            <StudentFocusRow
              key={student.student_id}
              student={student}
              programId={programId}
              sessionId={sessionId}
              date={date}
            />
          ))}
        </ul>
      )}
    </section>
  );
}

function DatePicker({
  date,
  onChange,
}: {
  date: string;
  onChange: (d: string) => void;
}) {
  const shift = (days: number) => {
    const [year, month, day] = date.split("-").map(Number);
    const d = new Date(year, month - 1, day);
    d.setDate(d.getDate() + days);
    const nextYear = d.getFullYear();
    const nextMonth = String(d.getMonth() + 1).padStart(2, "0");
    const nextDay = String(d.getDate()).padStart(2, "0");
    onChange(`${nextYear}-${nextMonth}-${nextDay}`);
  };
  return (
    <div className="flex items-center gap-1">
      <button
        aria-label="Previous day"
        onClick={() => shift(-1)}
        className="min-h-touch min-w-touch rounded-md border border-neutral-300 px-2 dark:border-neutral-700"
      >
        ‹
      </button>
      <button
        onClick={() => onChange(todayISO())}
        className="min-h-touch rounded-md border border-neutral-300 px-3 text-sm dark:border-neutral-700"
      >
        Today
      </button>
      <button
        aria-label="Next day"
        onClick={() => shift(1)}
        className="min-h-touch min-w-touch rounded-md border border-neutral-300 px-2 dark:border-neutral-700"
      >
        ›
      </button>
    </div>
  );
}

function PlanSkeleton() {
  return (
    <div className="space-y-3">
      {[0, 1].map((i) => (
        <div
          key={i}
          className="h-40 animate-pulse rounded-xl border border-neutral-200 bg-neutral-50 dark:border-neutral-800 dark:bg-neutral-900"
        />
      ))}
    </div>
  );
}
