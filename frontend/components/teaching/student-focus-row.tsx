"use client";

import { ExternalLink } from "lucide-react";
import { useMutation, useQueryClient } from "@tanstack/react-query";

import type { TeachingStudentFocus } from "@/lib/api/coach";
import {
  recordTestAttempt,
  updateSkillStatus,
  type SkillStatus,
} from "@/lib/api/curriculum";
import { queryKeys } from "@/lib/query/keys";

type SettableStatus = Extract<
  SkillStatus,
  "INTRODUCED" | "PRACTICING" | "NEEDS_REVIEW"
>;

const STATUS_LABEL: Record<string, string> = {
  NOT_STARTED: "Not started",
  INTRODUCED: "Introduced",
  LEARNING: "Learning",
  PRACTICING: "Practicing",
  TEST_READY: "Test ready",
  PASSED: "Passed",
  NEEDS_REVIEW: "Needs review",
};

const STATUS_BADGE: Record<string, string> = {
  NOT_STARTED:
    "bg-neutral-100 text-neutral-600 dark:bg-neutral-800 dark:text-neutral-300",
  INTRODUCED:
    "bg-neutral-100 text-neutral-600 dark:bg-neutral-800 dark:text-neutral-300",
  LEARNING: "bg-amber-100 text-amber-700 dark:bg-amber-950 dark:text-amber-300",
  PRACTICING:
    "bg-amber-100 text-amber-700 dark:bg-amber-950 dark:text-amber-300",
  TEST_READY: "bg-blue-100 text-blue-700 dark:bg-blue-950 dark:text-blue-300",
  PASSED: "bg-green-100 text-green-700 dark:bg-green-950 dark:text-green-300",
  NEEDS_REVIEW: "bg-red-100 text-red-700 dark:bg-red-950 dark:text-red-300",
};

const OUTCOMES: {
  key: string;
  label: string;
  status?: SettableStatus;
  mastered?: boolean;
  className: string;
}[] = [
  {
    key: "introduced",
    label: "Introduced",
    status: "INTRODUCED",
    className:
      "border-neutral-300 text-neutral-700 dark:border-neutral-700 dark:text-neutral-300",
  },
  {
    key: "practicing",
    label: "Practicing",
    status: "PRACTICING",
    className:
      "border-amber-300 text-amber-700 dark:border-amber-800 dark:text-amber-300",
  },
  {
    key: "mastered",
    label: "Mastered",
    mastered: true,
    className: "border-green-600 bg-green-600 text-white",
  },
  {
    key: "needs-review",
    label: "Needs review",
    status: "NEEDS_REVIEW",
    className:
      "border-red-300 text-red-700 dark:border-red-800 dark:text-red-300",
  },
];

const KEY_OF_STATUS: Record<SettableStatus, string> = {
  INTRODUCED: "introduced",
  PRACTICING: "practicing",
  NEEDS_REVIEW: "needs-review",
};

export function StudentFocusRow({
  student,
  programId,
  sessionId,
  date,
}: {
  student: TeachingStudentFocus;
  programId: string;
  sessionId: string;
  date: string;
}) {
  const queryClient = useQueryClient();
  const skill = student.next_skill;

  const invalidate = () => {
    void queryClient.invalidateQueries({
      queryKey: queryKeys.coach.todayPlan(date),
    });
    // Mastered/status writes also move the session skill board — refresh any
    // cached board so a coach toggling between views sees the new PASSED state.
    void queryClient.invalidateQueries({ queryKey: ["coach", "skill-board"] });
  };

  const statusMutation = useMutation({
    mutationFn: (status: SettableStatus) =>
      updateSkillStatus(student.student_id, skill!.skill_id, {
        program_id: programId,
        level_id: skill!.level_id,
        status,
      }),
    onSettled: invalidate,
  });

  const testMutation = useMutation({
    mutationFn: () =>
      recordTestAttempt(student.student_id, skill!.skill_id, {
        program_id: programId,
        level_id: skill!.level_id,
        attempts_count: 1,
        success_count: 1,
        session_id: sessionId,
      }),
    onSettled: invalidate,
  });

  const isPending = statusMutation.isPending || testMutation.isPending;
  const pendingKey = statusMutation.isPending
    ? KEY_OF_STATUS[statusMutation.variables as SettableStatus]
    : testMutation.isPending
      ? "mastered"
      : null;

  const doneKey = statusMutation.isSuccess
    ? KEY_OF_STATUS[statusMutation.variables as SettableStatus]
    : testMutation.isSuccess
      ? "mastered"
      : null;
  const doneLabel = doneKey
    ? (OUTCOMES.find((o) => o.key === doneKey)?.label ?? null)
    : null;
  const hasError = statusMutation.isError || testMutation.isError;

  // Level-up-ready: no next skill, no outcome buttons.
  if (!skill) {
    return (
      <li
        data-testid={`student-focus-${student.student_id}`}
        className="flex items-center justify-between gap-2 rounded-xl border border-green-200 bg-green-50 p-3 dark:border-green-900 dark:bg-green-950"
      >
        <span className="text-sm font-semibold">{student.student_name}</span>
        <span
          data-testid={`student-ready-${student.student_id}`}
          className="rounded-full bg-green-600 px-2.5 py-1 text-xs font-semibold text-white"
        >
          Ready to level up
        </span>
      </li>
    );
  }

  const isReview = skill.is_review || skill.status === "NEEDS_REVIEW";
  const youtube = skill.youtube_links[0];

  return (
    <li
      data-testid={`student-focus-${student.student_id}`}
      className={`space-y-2 rounded-xl border p-3 dark:bg-neutral-900 ${
        isReview
          ? "border-red-200 bg-red-50/50 dark:border-red-900 dark:bg-red-950/30"
          : "border-neutral-200 bg-white dark:border-neutral-800"
      }`}
    >
      <div className="flex items-start justify-between gap-2">
        <div className="min-w-0">
          <p className="text-sm font-semibold">{student.student_name}</p>
          <div className="mt-1 flex flex-wrap items-center gap-1.5">
            <span className="text-xs text-neutral-500">Next: {skill.name}</span>
            <span
              className={`rounded-full px-2 py-0.5 text-[10px] font-semibold ${
                STATUS_BADGE[skill.status] ?? STATUS_BADGE.NOT_STARTED
              }`}
            >
              {STATUS_LABEL[skill.status] ?? skill.status}
            </span>
            {isReview && (
              <span className="rounded-full bg-red-600 px-2 py-0.5 text-[10px] font-semibold text-white">
                Review
              </span>
            )}
          </div>
        </div>

        {youtube && (
          <a
            href={youtube.url}
            target="_blank"
            rel="noopener noreferrer"
            data-testid={`student-youtube-${student.student_id}`}
            aria-label={`Video for ${skill.name}`}
            className="inline-flex min-h-touch shrink-0 items-center gap-1 rounded-lg border border-red-200 bg-red-50 px-2.5 text-xs font-medium text-red-700 hover:bg-red-100 dark:border-red-900 dark:bg-red-950 dark:text-red-300"
          >
            <ExternalLink className="size-3.5" aria-hidden="true" />
            Video
          </a>
        )}
      </div>

      {doneLabel && (
        <p
          data-testid={`outcome-done-${student.student_id}`}
          className="text-xs font-medium text-green-700 dark:text-green-400"
        >
          ✓ {doneLabel} recorded
        </p>
      )}
      {hasError && (
        <p
          data-testid={`outcome-error-${student.student_id}`}
          className="text-xs text-red-600"
        >
          Couldn&apos;t save. Check connection and try again.
        </p>
      )}

      <div className="grid grid-cols-2 gap-2">
        {OUTCOMES.map((o) => {
          const saving = pendingKey === o.key;
          return (
            <button
              key={o.key}
              type="button"
              disabled={isPending}
              data-testid={`outcome-${student.student_id}-${o.key}`}
              onClick={() =>
                o.mastered
                  ? testMutation.mutate()
                  : statusMutation.mutate(o.status!)
              }
              className={`min-h-touch rounded-lg border px-2 text-xs font-semibold transition-all active:scale-95 disabled:opacity-50 ${o.className}`}
            >
              {saving ? "Saving…" : o.label}
            </button>
          );
        })}
      </div>
    </li>
  );
}
