"use client";

import { useState } from "react";
import { useParams, useSearchParams } from "next/navigation";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { CircleHelp } from "lucide-react";

import {
  getCoachSessionStudentsProgress,
  getStudentPassport,
  recommendLevelUp,
  recordTestAttempt,
  updateSkillStatus,
  type SkillPassportEntry,
  type SkillStatus,
} from "@/lib/api/curriculum";

const STATUS_LABELS: Record<SkillStatus, string> = {
  NOT_STARTED: "Not started",
  INTRODUCED: "Introduced",
  LEARNING: "Learning",
  PRACTICING: "Practicing",
  TEST_READY: "Test ready",
  PASSED: "Passed",
  NEEDS_REVIEW: "Needs review",
};

const STATUS_ORDER: SkillStatus[] = [
  "NOT_STARTED",
  "INTRODUCED",
  "LEARNING",
  "PRACTICING",
  "TEST_READY",
  "PASSED",
  "NEEDS_REVIEW",
];

const TEST_ATTEMPT_HINT =
  "Attempts = total tries. Successes = correct tries. Examples: 1/1 means one correct try; 10/7 passes at 70%; 10/5 needs review.";

function statusColor(status: SkillStatus): string {
  switch (status) {
    case "PASSED":
      return "bg-green-100 text-green-800";
    case "TEST_READY":
      return "bg-blue-100 text-blue-800";
    case "LEARNING":
    case "PRACTICING":
      return "bg-yellow-100 text-yellow-800";
    case "NEEDS_REVIEW":
      return "bg-red-100 text-red-800";
    default:
      return "bg-neutral-100 text-neutral-500";
  }
}

export default function CoachStudentPassportPage() {
  const { studentId } = useParams<{ studentId: string }>();
  const searchParams = useSearchParams();
  const programId = searchParams.get("program_id") ?? "";
  const fromSession = searchParams.get("from_session") ?? "";
  const studentNameParam = searchParams.get("student_name") ?? "";
  const queryClient = useQueryClient();

  const passportKey = ["coach", "passport", studentId, programId || "default"];

  const { data, isLoading, isError, refetch } = useQuery({
    queryKey: passportKey,
    queryFn: () => getStudentPassport(studentId, programId || undefined),
    enabled: Boolean(studentId),
  });

  const { data: sessionRows } = useQuery({
    queryKey: ["coach", "session-progress", fromSession, programId || "default"],
    queryFn: () => getCoachSessionStudentsProgress(fromSession, programId || undefined),
    enabled: Boolean(fromSession) && !studentNameParam,
    staleTime: 2 * 60 * 1000,
  });

  const levelUpMutation = useMutation({
    mutationFn: () => recommendLevelUp(studentId, programId || undefined),
    onSuccess: () => void queryClient.invalidateQueries({ queryKey: passportKey }),
  });

  const skills = data ?? [];
  const requiredSkills = skills.filter((s) => s.is_required);
  const allRequiredPassed = requiredSkills.length > 0 && requiredSkills.every((s) => s.status === "PASSED");
  const resolvedStudentName =
    studentNameParam ||
    sessionRows?.find((row) => row.student_id === studentId)?.student_name ||
    `Student ${studentId}`;

  return (
    <section data-testid="coach-student-passport" className="space-y-4">
      <div className="flex flex-col gap-3 min-[420px]:flex-row min-[420px]:items-start min-[420px]:justify-between">
        <div className="min-w-0">
          <h1 className="text-xl font-semibold">Skill Passport</h1>
          <p className="text-sm text-neutral-500">{resolvedStudentName}</p>
        </div>
        <button
          disabled={!allRequiredPassed || levelUpMutation.isPending}
          onClick={() => levelUpMutation.mutate()}
          className="min-h-touch rounded-lg bg-blue-600 px-4 py-2 text-sm font-semibold text-white transition-all active:scale-95 disabled:cursor-not-allowed disabled:opacity-40"
        >
          {levelUpMutation.isPending ? "Recommending..." : "Recommend Level Up"}
        </button>
      </div>

      {levelUpMutation.isSuccess && (
        <p className="rounded-md bg-green-50 p-3 text-sm text-green-700">
          Level-up recommendation submitted.
        </p>
      )}
      {levelUpMutation.isError && (
        <p className="rounded-md bg-red-50 p-3 text-sm text-red-700">
          Failed to submit recommendation.
        </p>
      )}

      {isError && (
        <div role="alert" className="rounded-md bg-red-50 p-3 text-sm text-red-700">
          <p>Couldn&apos;t load skill passport. Try again.</p>
          <button
            onClick={() => void refetch()}
            className="mt-2 min-h-[36px] rounded-md border border-red-200 px-3 text-sm font-medium"
          >
            Retry
          </button>
        </div>
      )}

      {isLoading ? (
        <SkeletonList />
      ) : isError ? null : skills.length === 0 ? (
        <p className="text-sm text-neutral-500">No skills found for this student/program.</p>
      ) : (
        <ul className="space-y-3">
          {skills.map((entry) => (
            <SkillCard
              key={entry.skill_id}
              entry={entry}
              studentId={studentId}
              onUpdated={() => void queryClient.invalidateQueries({ queryKey: passportKey })}
            />
          ))}
        </ul>
      )}
    </section>
  );
}

function SkillCard({
  entry,
  studentId,
  onUpdated,
}: {
  entry: SkillPassportEntry;
  studentId: string;
  onUpdated: () => void;
}) {
  const [showTestForm, setShowTestForm] = useState(false);
  const [attemptsCount, setAttemptsCount] = useState("1");
  const [successCount, setSuccessCount] = useState("1");
  const [notes, setNotes] = useState("");

  const statusMutation = useMutation({
    mutationFn: (status: SkillStatus) =>
      updateSkillStatus(studentId, entry.skill_id, {
        program_id: entry.program_id,
        level_id: entry.level_id,
        status,
      }),
    onSuccess: onUpdated,
  });

  const testMutation = useMutation({
    mutationFn: () =>
      recordTestAttempt(studentId, entry.skill_id, {
        program_id: entry.program_id,
        level_id: entry.level_id,
        attempts_count: parseInt(attemptsCount, 10),
        success_count: parseInt(successCount, 10),
        notes: notes.trim() || undefined,
      }),
    onSuccess: () => {
      onUpdated();
      setShowTestForm(false);
      setAttemptsCount("1");
      setSuccessCount("1");
      setNotes("");
    },
  });

  return (
    <li className="rounded-xl border border-neutral-200 bg-white p-4 dark:border-neutral-800 dark:bg-neutral-900">
      {/* Header row */}
      <div className="mb-3 flex flex-col gap-2 min-[420px]:flex-row min-[420px]:items-start min-[420px]:justify-between">
        <div className="flex-1 min-w-0">
          <div className="flex items-center gap-2 flex-wrap">
            <span className="text-sm font-semibold text-rally-base">{entry.skill_name}</span>
            {entry.is_required && (
              <span className="rounded-full bg-red-50 px-2 py-0.5 text-[10px] font-bold uppercase text-red-600">
                Required
              </span>
            )}
          </div>
          {entry.skill_description && (
            <p className="mt-0.5 text-xs text-neutral-400 line-clamp-2">{entry.skill_description}</p>
          )}
        </div>
        <span
          className={`shrink-0 rounded-full px-2.5 py-1 text-xs font-semibold ${statusColor(entry.status)}`}
        >
          {STATUS_LABELS[entry.status]}
        </span>
      </div>

      {/* Test info */}
      {entry.test_attempt_count > 0 && (
        <p className="mb-3 text-xs text-neutral-400">
          {entry.test_attempt_count} test attempt{entry.test_attempt_count !== 1 ? "s" : ""}
          {entry.last_tested_at && (
            <> · last{" "}
              {new Date(entry.last_tested_at).toLocaleDateString(undefined, {
                month: "short",
                day: "numeric",
              })}
            </>
          )}
          {entry.last_test_passed !== null && (
            <> · last result: {entry.last_test_passed ? "passed" : "failed"}</>
          )}
        </p>
      )}

      {/* Controls */}
      <div className="grid gap-2 min-[360px]:grid-cols-[minmax(0,1fr)_auto]">
        <select
          value={entry.status}
          onChange={(e) => statusMutation.mutate(e.target.value as SkillStatus)}
          disabled={statusMutation.isPending}
          className="min-h-[36px] min-w-0 rounded-lg border border-neutral-300 bg-white px-2 py-1.5 text-xs font-medium focus:border-blue-500 focus:outline-none dark:border-neutral-700 dark:bg-neutral-800"
        >
          {STATUS_ORDER.map((s) => (
            <option key={s} value={s}>
              {STATUS_LABELS[s]}
            </option>
          ))}
        </select>

        <button
          onClick={() => setShowTestForm((v) => !v)}
          className="min-h-[36px] rounded-lg border border-neutral-300 px-3 py-1.5 text-xs font-medium text-neutral-700 transition-colors hover:bg-neutral-50 dark:border-neutral-700 dark:text-neutral-300"
        >
          {showTestForm ? "Cancel" : "Record Test"}
        </button>
      </div>

      {/* Test form */}
      {showTestForm && (
        <div className="mt-3 rounded-lg bg-neutral-50 p-3 dark:bg-neutral-800">
          <div className="grid grid-cols-2 gap-2 mb-2">
            <div>
              <label className="mb-1 flex items-center gap-1 text-[11px] font-medium text-neutral-500">
                Attempts
                <FieldHint message={TEST_ATTEMPT_HINT} />
              </label>
              <input
                type="number"
                min="1"
                value={attemptsCount}
                onChange={(e) => setAttemptsCount(e.target.value)}
                className="w-full rounded-md border border-neutral-300 px-2 py-1.5 text-sm focus:border-blue-500 focus:outline-none"
              />
            </div>
            <div>
              <label className="mb-1 flex items-center gap-1 text-[11px] font-medium text-neutral-500">
                Successes
                <FieldHint message={TEST_ATTEMPT_HINT} align="end" />
              </label>
              <input
                type="number"
                min="0"
                value={successCount}
                onChange={(e) => setSuccessCount(e.target.value)}
                className="w-full rounded-md border border-neutral-300 px-2 py-1.5 text-sm focus:border-blue-500 focus:outline-none"
              />
            </div>
          </div>
          <div className="mb-2">
            <label className="mb-1 block text-[11px] font-medium text-neutral-500">Notes (optional)</label>
            <input
              type="text"
              value={notes}
              onChange={(e) => setNotes(e.target.value)}
              placeholder="Any observations..."
              className="w-full rounded-md border border-neutral-300 px-2 py-1.5 text-sm focus:border-blue-500 focus:outline-none"
            />
          </div>
          {testMutation.isError && (
            <p className="mb-2 text-xs text-red-600">Failed to record test.</p>
          )}
          <button
            disabled={testMutation.isPending}
            onClick={() => testMutation.mutate()}
            className="w-full min-h-[36px] rounded-lg bg-blue-600 text-sm font-semibold text-white transition-all active:scale-95 disabled:opacity-60"
          >
            {testMutation.isPending ? "Saving..." : "Save Test"}
          </button>
        </div>
      )}
    </li>
  );
}

function FieldHint({
  message,
  align = "start",
}: {
  message: string;
  align?: "start" | "end";
}) {
  return (
    <span
      tabIndex={0}
      aria-label={message}
      className="group relative inline-flex text-neutral-400 focus:outline-none"
    >
      <CircleHelp className="size-3.5" aria-hidden="true" />
      <span
        role="tooltip"
        className={`pointer-events-none absolute top-5 z-20 w-64 rounded-md bg-neutral-900 px-3 py-2 text-left text-[11px] font-medium leading-4 text-white opacity-0 shadow-lg transition-opacity group-hover:opacity-100 group-focus:opacity-100 ${
          align === "end" ? "right-0" : "left-0"
        }`}
      >
        {message}
      </span>
    </span>
  );
}

function SkeletonList() {
  return (
    <div className="space-y-3">
      {[0, 1, 2, 3].map((i) => (
        <div key={i} className="h-24 animate-pulse rounded-xl bg-neutral-100 dark:bg-neutral-800" />
      ))}
    </div>
  );
}
