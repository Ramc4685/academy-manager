"use client";

import Link from "next/link";
import { useParams, useSearchParams } from "next/navigation";
import { useQuery } from "@tanstack/react-query";

import {
  getCoachSessionStudentsProgress,
  type StudentProgressOverview,
} from "@/lib/api/curriculum";

export default function CoachSessionProgressPage() {
  const { id: sessionId } = useParams<{ id: string }>();
  const searchParams = useSearchParams();
  const programId = searchParams.get("program_id") ?? "";

  const { data: rows, isLoading, isError } = useQuery({
    queryKey: ["coach", "session-progress", sessionId, programId],
    queryFn: () => getCoachSessionStudentsProgress(sessionId, programId),
    enabled: Boolean(sessionId) && Boolean(programId),
    staleTime: 2 * 60 * 1000,
  });

  const progressRows = rows ?? [];

  return (
    <section data-testid="coach-session-progress" className="space-y-4">
      <div>
        <h1 className="text-xl font-semibold">Session Progress</h1>
        <p className="text-sm text-neutral-500">
          {progressRows.length} student{progressRows.length !== 1 ? "s" : ""} in this session
        </p>
      </div>

      {!programId && (
        <p role="alert" className="rounded-md bg-amber-50 p-3 text-sm text-amber-800">
          Select a program before viewing skill progress.
        </p>
      )}

      {isError && (
        <p role="alert" className="rounded-md bg-red-50 p-3 text-sm text-red-700">
          Could not load session progress.
        </p>
      )}

      {!programId ? null : isLoading ? (
        <SkeletonList />
      ) : progressRows.length === 0 ? (
        <p className="text-sm text-neutral-500">No students on roster.</p>
      ) : (
        <ul className="space-y-2" data-testid="session-progress-list">
          {progressRows.map((entry) => (
            <StudentProgressRow
              key={entry.student_id}
              progress={entry}
              sessionId={sessionId}
            />
          ))}
        </ul>
      )}
    </section>
  );
}

function StudentProgressRow({
  progress,
  sessionId,
}: {
  progress: StudentProgressOverview;
  sessionId: string;
}) {
  const passportHref = `/coach/students/${encodeURIComponent(progress.student_id)}/passport?program_id=${encodeURIComponent(progress.program_id)}&from_session=${encodeURIComponent(sessionId)}`;

  const passedPct =
    progress.total_skill_count > 0
      ? Math.round((progress.total_skills_passed / progress.total_skill_count) * 100)
      : null;

  return (
    <li>
      <Link
        href={passportHref as Parameters<typeof Link>[0]["href"]}
        className="flex items-center gap-3 rounded-xl border border-neutral-200 bg-white px-4 py-3 transition-all hover:border-blue-300 hover:shadow-sm active:scale-[0.99] dark:border-neutral-800 dark:bg-neutral-900"
        data-testid={`session-progress-student-${progress.student_id}`}
      >
        {/* Avatar */}
        <div className="flex h-9 w-9 shrink-0 items-center justify-center rounded-full bg-blue-100 text-sm font-bold text-blue-700">
          {progress.student_name[0]?.toUpperCase() ?? "?"}
        </div>

        {/* Name + level */}
        <div className="min-w-0 flex-1">
          <p className="truncate text-sm font-semibold text-rally-base">{progress.student_name}</p>
          <p className="truncate text-xs text-neutral-500">
            {progress.current_level_name ?? "Not placed"} · {progress.program_name}
          </p>
        </div>

        {/* Skill summary */}
        <div className="shrink-0 text-right">
          <p className="text-sm font-semibold text-rally-base">
            {progress.total_skills_passed}/{progress.total_skill_count}
          </p>
          <p className="text-[11px] text-neutral-400">skills passed</p>
          {passedPct !== null && (
            <div className="mt-1 h-1.5 w-16 overflow-hidden rounded-full bg-neutral-200">
              <div
                className="h-full rounded-full bg-green-500"
                style={{ width: `${passedPct}%` }}
              />
            </div>
          )}
        </div>

        {/* Chevron */}
        <svg
          width="14"
          height="14"
          viewBox="0 0 24 24"
          fill="none"
          stroke="currentColor"
          strokeWidth="2.5"
          strokeLinecap="round"
          strokeLinejoin="round"
          className="ml-1 shrink-0 text-neutral-400"
        >
          <polyline points="9 18 15 12 9 6" />
        </svg>
      </Link>
    </li>
  );
}

function SkeletonList() {
  return (
    <div className="space-y-2">
      {[0, 1, 2, 3].map((i) => (
        <div key={i} className="h-16 animate-pulse rounded-xl bg-neutral-100 dark:bg-neutral-800" />
      ))}
    </div>
  );
}
