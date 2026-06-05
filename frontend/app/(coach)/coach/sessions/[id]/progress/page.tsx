"use client";

import Link from "next/link";
import { useParams, useSearchParams } from "next/navigation";
import { useQuery } from "@tanstack/react-query";

import { getSessionRoster } from "@/lib/api/coach";
import { getStudentProgress } from "@/lib/api/curriculum";
import { queryKeys } from "@/lib/query/keys";

export default function CoachSessionProgressPage() {
  const { id: sessionId } = useParams<{ id: string }>();
  const searchParams = useSearchParams();
  const programId = searchParams.get("program_id") ?? "";

  const { data: rosterData, isLoading, isError } = useQuery({
    queryKey: queryKeys.coach.session(sessionId),
    queryFn: () => getSessionRoster(sessionId),
    enabled: Boolean(sessionId),
    staleTime: 2 * 60 * 1000,
  });

  const roster = rosterData?.roster ?? [];

  return (
    <section data-testid="coach-session-progress" className="space-y-4">
      <div>
        <h1 className="text-xl font-semibold">Session Progress</h1>
        <p className="text-sm text-neutral-500">
          {roster.length} student{roster.length !== 1 ? "s" : ""} in this session
        </p>
      </div>

      {isError && (
        <p role="alert" className="rounded-md bg-red-50 p-3 text-sm text-red-700">
          Could not load roster.
        </p>
      )}

      {isLoading ? (
        <SkeletonList />
      ) : roster.length === 0 ? (
        <p className="text-sm text-neutral-500">No students on roster.</p>
      ) : (
        <ul className="space-y-2" data-testid="session-progress-list">
          {roster.map((entry) => (
            <StudentProgressRow
              key={entry.student_id}
              studentId={entry.student_id}
              fullName={entry.full_name}
              programId={programId}
              sessionId={sessionId}
            />
          ))}
        </ul>
      )}
    </section>
  );
}

function StudentProgressRow({
  studentId,
  fullName,
  programId,
  sessionId,
}: {
  studentId: string;
  fullName: string;
  programId: string;
  sessionId: string;
}) {
  const { data: progress } = useQuery({
    queryKey: ["coach", "student-progress", studentId, programId],
    queryFn: () => getStudentProgress(studentId, programId),
    enabled: Boolean(studentId) && Boolean(programId),
    staleTime: 5 * 60 * 1000,
  });

  const passportHref = `/coach/students/${encodeURIComponent(studentId)}/passport?program_id=${encodeURIComponent(programId)}&from_session=${encodeURIComponent(sessionId)}`;

  const passedPct =
    progress && progress.total_skills > 0
      ? Math.round((progress.passed_skills / progress.total_skills) * 100)
      : null;

  return (
    <li>
      <Link
        href={passportHref as Parameters<typeof Link>[0]["href"]}
        className="flex items-center gap-3 rounded-xl border border-neutral-200 bg-white px-4 py-3 transition-all hover:border-blue-300 hover:shadow-sm active:scale-[0.99] dark:border-neutral-800 dark:bg-neutral-900"
        data-testid={`session-progress-student-${studentId}`}
      >
        {/* Avatar */}
        <div className="flex h-9 w-9 shrink-0 items-center justify-center rounded-full bg-blue-100 text-sm font-bold text-blue-700">
          {fullName[0]?.toUpperCase() ?? "?"}
        </div>

        {/* Name + level */}
        <div className="min-w-0 flex-1">
          <p className="truncate text-sm font-semibold text-rally-base">{fullName}</p>
          {progress ? (
            <p className="truncate text-xs text-neutral-500">
              {progress.current_level_name ?? "Not placed"} · {progress.program_name}
            </p>
          ) : (
            <p className="text-xs text-neutral-400">Loading...</p>
          )}
        </div>

        {/* Skill summary */}
        {progress ? (
          <div className="shrink-0 text-right">
            <p className="text-sm font-semibold text-rally-base">
              {progress.passed_skills}/{progress.total_skills}
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
        ) : programId ? (
          <div className="h-4 w-16 animate-pulse rounded bg-neutral-100 dark:bg-neutral-800" />
        ) : null}

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
