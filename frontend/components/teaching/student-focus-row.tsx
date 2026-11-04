"use client";

import { useState } from "react";
import { ExternalLink } from "lucide-react";
import { useMutation, useQueryClient } from "@tanstack/react-query";

import type { TeachingStudentFocus } from "@/components/teaching/types";
import {
  recordTestAttempt,
  updateSkillStatus,
  type SkillStatus,
} from "@/lib/api/curriculum";
import { queryKeys } from "@/lib/query/keys";
import { SKILL_STATUS_LABELS, SkillStatusChip } from "@/components/skills/SkillStatusChip";

type SettableStatus = Extract<
  SkillStatus,
  "INTRODUCED" | "PRACTICING" | "NEEDS_REVIEW"
>;

/**
 * The one-tap outcomes, named with the SAME seven-state vocabulary the header
 * badge, the skills page, the passport and the skill board use (#895). The
 * quick-pass button used to read "Mastered" while the badge it moved read
 * "Passed" — one status, two words, on one screen. `PASSED` is deliberately
 * reached through `recordTestAttempt`, not `updateSkillStatus`: the backend's
 * CoachSettableStatus rejects PASSED (see the coach passport page).
 */
const OUTCOMES: {
  key: string;
  label: string;
  status?: SettableStatus;
  passed?: boolean;
  className: string;
}[] = [
  {
    key: "introduced",
    label: SKILL_STATUS_LABELS.INTRODUCED,
    status: "INTRODUCED",
    className:
      "border-neutral-300 text-neutral-700 dark:border-neutral-700 dark:text-neutral-300",
  },
  {
    key: "practicing",
    label: SKILL_STATUS_LABELS.PRACTICING,
    status: "PRACTICING",
    className:
      "border-amber-300 text-amber-700 dark:border-amber-800 dark:text-amber-300",
  },
  {
    key: "passed",
    label: SKILL_STATUS_LABELS.PASSED,
    passed: true,
    className: "border-green-600 bg-green-600 text-white",
  },
  {
    key: "needs-review",
    label: SKILL_STATUS_LABELS.NEEDS_REVIEW,
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

/**
 * Which outcome button, if any, the skill's CURRENT status corresponds to.
 * LEARNING / TEST_READY / NOT_STARTED have no one-tap button — they are set
 * from the fuller skills page — so they light nothing up.
 */
const KEY_OF_CURRENT_STATUS: Record<string, string> = {
  INTRODUCED: "introduced",
  PRACTICING: "practicing",
  PASSED: "passed",
  NEEDS_REVIEW: "needs-review",
};

const SETTABLE: readonly SettableStatus[] = [
  "INTRODUCED",
  "PRACTICING",
  "NEEDS_REVIEW",
];

function asSettable(status: string): SettableStatus | null {
  return (SETTABLE as readonly string[]).includes(status)
    ? (status as SettableStatus)
    : null;
}

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
  /**
   * The status this skill held just before the coach's last status tap, kept
   * so the row can offer a one-tap revert (#895). Only a status the coach may
   * set again is stored: PASSED is recorded through the test endpoint and has
   * no "un-record", and NOT_STARTED is not coach-settable, so a tap that moved
   * the skill off either of those simply offers no Undo rather than an Undo
   * that would 500.
   */
  const [undoTo, setUndoTo] = useState<SettableStatus | null>(null);

  const invalidate = () => {
    void queryClient.invalidateQueries({
      queryKey: queryKeys.coach.todayPlan(date),
    });
    // Passed/status writes also move the session skill board — refresh any
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
      ? "passed"
      : null;

  const doneKey = statusMutation.isSuccess
    ? KEY_OF_STATUS[statusMutation.variables as SettableStatus]
    : testMutation.isSuccess
      ? "passed"
      : null;
  const doneLabel = doneKey
    ? (OUTCOMES.find((o) => o.key === doneKey)?.label ?? null)
    : null;
  const hasError = statusMutation.isError || testMutation.isError;

  if (!skill) return <ReadyForLevelUpRow student={student} />;

  // What the skill is right now, so the buttons read as a state and not only
  // as four equal commands.
  const activeKey = KEY_OF_CURRENT_STATUS[skill.status] ?? null;

  function applyStatus(next: SettableStatus) {
    const previous = asSettable(skill!.status);
    setUndoTo(previous && previous !== next ? previous : null);
    statusMutation.mutate(next);
  }

  const { isReview, youtube } = focusRowMeta(student);

  return (
    <li data-testid={`student-focus-${student.student_id}`} className={focusRowClass(isReview)}>
      <StudentFocusHeader student={student} youtube={youtube} isReview={isReview} />

      {doneLabel && (
        <p
          data-testid={`outcome-done-${student.student_id}`}
          className="flex flex-wrap items-center gap-2 text-xs font-medium text-green-700 dark:text-green-400"
        >
          <span>✓ {doneLabel} recorded</span>
          {/* Only once the write it reverts has actually landed. */}
          {undoTo !== null && statusMutation.isSuccess && (
            <button
              type="button"
              disabled={isPending}
              data-testid={`outcome-undo-${student.student_id}`}
              onClick={() => {
                const target = undoTo;
                setUndoTo(null);
                if (target) statusMutation.mutate(target);
              }}
              className="min-h-touch rounded-lg border border-neutral-300 px-2 text-xs font-semibold text-neutral-700 underline underline-offset-2 disabled:opacity-50 dark:border-neutral-700 dark:text-neutral-300"
            >
              Undo — back to {SKILL_STATUS_LABELS[undoTo]}
            </button>
          )}
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
          const active = activeKey === o.key;
          return (
            <button
              key={o.key}
              type="button"
              disabled={isPending}
              // #895: the buttons are a state, not four equal commands — the
              // one the skill is already in is pressed. `aria-pressed` carries
              // that to screen readers; the ring carries it to everyone else,
              // so it never rests on colour alone.
              aria-pressed={active}
              data-testid={`outcome-${student.student_id}-${o.key}`}
              onClick={() => {
                if (o.passed) {
                  setUndoTo(null);
                  testMutation.mutate();
                  return;
                }
                applyStatus(o.status!);
              }}
              className={`min-h-touch rounded-lg border px-2 text-xs font-semibold transition-all active:scale-95 disabled:opacity-50 ${o.className} ${
                active
                  ? "ring-2 ring-neutral-900 ring-offset-1 dark:ring-neutral-100 dark:ring-offset-neutral-900"
                  : ""
              }`}
            >
              {saving ? "Saving…" : o.label}
              {active && <span className="sr-only"> — current state</span>}
            </button>
          );
        })}
      </div>
    </li>
  );
}

export function StudentFocusReadOnlyRow({
  student,
}: {
  student: TeachingStudentFocus;
}) {
  if (!student.next_skill) return <ReadyForLevelUpRow student={student} />;

  const { isReview, youtube } = focusRowMeta(student);
  return (
    <li data-testid={`student-focus-${student.student_id}`} className={focusRowClass(isReview)}>
      <StudentFocusHeader student={student} youtube={youtube} isReview={isReview} />
    </li>
  );
}

function ReadyForLevelUpRow({ student }: { student: TeachingStudentFocus }) {
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

function focusRowMeta(student: TeachingStudentFocus) {
  const skill = student.next_skill!;
  return {
    isReview: skill.is_review || skill.status === "NEEDS_REVIEW",
    youtube: skill.youtube_links[0],
  };
}

function focusRowClass(isReview: boolean): string {
  return `space-y-2 rounded-xl border p-3 dark:bg-neutral-900 ${
    isReview
      ? "border-red-200 bg-red-50/50 dark:border-red-900 dark:bg-red-950/30"
      : "border-neutral-200 bg-white dark:border-neutral-800"
  }`;
}

function StudentFocusHeader({
  student,
  youtube,
  isReview,
}: {
  student: TeachingStudentFocus;
  youtube?: { url: string };
  isReview: boolean;
}) {
  const skill = student.next_skill!;
  return (
    <div className="flex items-start justify-between gap-2">
      <div className="min-w-0">
        <p className="text-sm font-semibold">{student.student_name}</p>
        <div className="mt-1 flex flex-wrap items-center gap-1.5">
          <span className="text-xs text-neutral-500">Next: {skill.name}</span>
          <SkillStatusChip status={skill.status} size="sm" />
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
  );
}
