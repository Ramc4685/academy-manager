"use client";

import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { markCoachSkillMastered, unmarkCoachSkillMastered } from "@/lib/api/coach";
import { getCoachSessionSkillBoard, type SkillBoardLevelGroup } from "@/lib/api/curriculum";
import { queryKeys } from "@/lib/query/keys";

interface Selection {
  levelId: string;
  skillId: string;
}

interface LevelUpNotice {
  studentId: string;
  studentName: string;
  skillId: string;
  levelLabel: string;
}

function levelLabel(group: SkillBoardLevelGroup): string {
  return `Level ${group.sequence} · ${group.level_name}`;
}

/** First skill that someone in the level still needs: today's most likely lesson. */
function defaultSelection(groups: SkillBoardLevelGroup[]): Selection | null {
  for (const group of groups) {
    const skill = group.skills.find((s) =>
      group.students.some((st) => st.statuses[s.skill_id]?.status !== "PASSED"),
    );
    if (skill) return { levelId: group.level_id, skillId: skill.skill_id };
  }
  const first = groups[0];
  return first?.skills[0] ? { levelId: first.level_id, skillId: first.skills[0].skill_id } : null;
}

/**
 * Tap mode: pick the skill taught today, tap each student who got it. Ticking
 * the last skill of a level queues the move up; it lands this evening unless
 * the tap is undone.
 */
export function TapSkillsWorkspace({
  occurrenceId,
  sessionId,
  date,
  programId: requestedProgramId,
  onUpdated,
}: {
  occurrenceId: string;
  sessionId: string;
  date: string;
  /** The page's `program_id`; omitted means the academy's default curriculum. */
  programId?: string;
  /** Lets the page refresh the By skill / By student data too. */
  onUpdated?: () => void;
}) {
  const queryClient = useQueryClient();
  const boardKey = queryKeys.coach.skillBoard(sessionId, requestedProgramId);
  const { data: board, isLoading, isError } = useQuery({
    queryKey: boardKey,
    queryFn: () => getCoachSessionSkillBoard(sessionId, requestedProgramId),
  });
  const [picked, setPicked] = useState<Selection | null>(null);
  const [notice, setNotice] = useState<LevelUpNotice | null>(null);
  const [pendingIds, setPendingIds] = useState<string[]>([]);

  const groups = board?.groups ?? [];
  const selection = picked ?? defaultSelection(groups);
  const group = groups.find((g) => g.level_id === selection?.levelId);
  const skill = group?.skills.find((s) => s.skill_id === selection?.skillId);
  const programId = board?.program_id ?? "";

  const refresh = () => {
    onUpdated?.();
    return queryClient.invalidateQueries({ queryKey: boardKey });
  };
  // Pin the default skill on the first tap: otherwise, once everyone has it,
  // the default moves to the next skill under the coach's thumb.
  const pinSelection = () => {
    if (!picked && selection) setPicked(selection);
  };

  const mark = useMutation({
    mutationFn: (studentIds: string[]) =>
      markCoachSkillMastered(
        occurrenceId,
        skill!.skill_id,
        { program_id: programId, student_ids: studentIds },
        date,
      ),
    onMutate: (studentIds) => {
      pinSelection();
      setPendingIds(studentIds);
    },
    onSuccess: ({ results }) => {
      const finished = results.find((r) => r.level_up_queued && r.outcome === "mastered");
      const student = group?.students.find((s) => s.student_id === finished?.student_id);
      if (finished && student && group && skill) {
        setNotice({
          studentId: student.student_id,
          studentName: student.student_name,
          skillId: skill.skill_id,
          levelLabel: levelLabel(group),
        });
      }
    },
    onSettled: async () => {
      await refresh();
      setPendingIds([]);
    },
  });

  const unmark = useMutation({
    mutationFn: (args: { studentId: string; skillId: string }) =>
      unmarkCoachSkillMastered(occurrenceId, args.studentId, args.skillId, { programId, date }),
    onMutate: (args) => {
      pinSelection();
      setPendingIds([args.studentId]);
    },
    onSuccess: (_result, args) => {
      if (notice?.studentId === args.studentId) setNotice(null);
    },
    onSettled: async () => {
      await refresh();
      setPendingIds([]);
    },
  });

  if (isLoading) return <div className="h-40 animate-pulse rounded-lg bg-neutral-100" />;
  if (isError || !board) {
    return (
      <p role="alert" className="rounded-md bg-red-50 p-3 text-sm text-red-700">
        Couldn&apos;t load this class&apos;s skills.
      </p>
    );
  }
  if (!group || !skill) {
    return (
      <p className="rounded-md bg-neutral-50 p-3 text-sm text-neutral-600">
        No one in this class is placed on a level yet. Place students from the Progress tab first.
      </p>
    );
  }

  const missing = group.students.filter((s) => s.statuses[skill.skill_id]?.status !== "PASSED");
  const busy = mark.isPending || unmark.isPending;

  return (
    <div data-testid="coach-tap-skills" className="space-y-4">
      {notice && (
        <div
          role="status"
          className="flex items-start gap-3 rounded-xl bg-rally-volt-400 p-3 text-rally-ink"
        >
          <div className="flex-1 text-sm">
            <p className="font-display text-base font-bold">
              {notice.studentName} finished {notice.levelLabel}
            </p>
            <p>Moves up this evening, with a certificate. Tapped by mistake? Undo it now.</p>
          </div>
          <button
            type="button"
            disabled={busy}
            onClick={() => unmark.mutate({ studentId: notice.studentId, skillId: notice.skillId })}
            className="min-h-touch rounded-md border-2 border-rally-ink px-3 text-sm font-bold disabled:opacity-50"
          >
            Undo
          </button>
        </div>
      )}

      <section className="space-y-3">
        <h2 className="font-display text-base font-bold text-rally-ink">
          1. What did you teach today?
        </h2>
        {groups.map((g) => (
          <div key={g.level_id} className="space-y-1.5">
            <p className="text-xs font-bold text-status-slate-600">{levelLabel(g)}</p>
            <div className="flex flex-wrap gap-1.5">
              {g.skills.map((s) => {
                const active = g.level_id === group.level_id && s.skill_id === skill.skill_id;
                return (
                  <button
                    key={s.skill_id}
                    type="button"
                    aria-pressed={active}
                    onClick={() => setPicked({ levelId: g.level_id, skillId: s.skill_id })}
                    className={`min-h-touch rounded-full border-2 px-3 text-sm font-semibold ${
                      active
                        ? "border-rally-cobalt bg-rally-cobalt text-white"
                        : "border-rally-line bg-white text-rally-ink"
                    }`}
                  >
                    {s.name}
                  </button>
                );
              })}
            </div>
          </div>
        ))}
      </section>

      <section className="space-y-2">
        <div className="flex items-center justify-between gap-2">
          <h2 className="font-display text-base font-bold text-rally-ink">
            2. Who got &ldquo;{skill.name}&rdquo;?
          </h2>
          <button
            type="button"
            disabled={busy || missing.length === 0}
            onClick={() => mark.mutate(missing.map((s) => s.student_id))}
            className="min-h-touch px-1 text-sm font-bold text-rally-cobalt-700 disabled:opacity-40"
          >
            Everyone
          </button>
        </div>
        <ul className="space-y-2">
          {group.students.map((student) => {
            const has = student.statuses[skill.skill_id]?.status === "PASSED";
            const pending = pendingIds.includes(student.student_id);
            const movingUp = student.level_up_status === "RECOMMENDED";
            const pct = student.required_total
              ? Math.round((student.required_passed / student.required_total) * 100)
              : 0;
            return (
              <li key={student.student_id}>
                <button
                  type="button"
                  aria-pressed={has}
                  disabled={busy}
                  onClick={() =>
                    has
                      ? unmark.mutate({ studentId: student.student_id, skillId: skill.skill_id })
                      : mark.mutate([student.student_id])
                  }
                  className={`flex min-h-16 w-full items-center gap-3 rounded-xl border-2 p-3 text-left disabled:cursor-wait ${
                    has
                      ? "border-status-green-500 bg-status-green-50"
                      : "border-rally-line bg-white"
                  } ${pending ? "opacity-60" : ""}`}
                >
                  <span className="flex min-w-0 flex-1 flex-col gap-1.5">
                    <span className="truncate text-sm font-bold text-rally-ink">
                      {student.student_name}
                    </span>
                    <span className="block h-1.5 overflow-hidden rounded-full bg-rally-line">
                      <span
                        className="block h-full rounded-full bg-rally-cobalt"
                        style={{ width: `${pct}%` }}
                      />
                    </span>
                    <span className="text-xs text-status-slate-600">
                      {movingUp
                        ? "All skills done · moves up this evening"
                        : `${student.required_passed} of ${student.required_total} skills`}
                    </span>
                  </span>
                  {has ? (
                    <span className="rounded-full bg-status-green-800 px-3 py-1 text-sm font-bold text-white">
                      Got it
                    </span>
                  ) : (
                    <span className="rounded-full border-2 border-dashed border-rally-subtle px-3 py-1 text-sm font-semibold text-status-slate-600">
                      Tap
                    </span>
                  )}
                </button>
              </li>
            );
          })}
        </ul>
        {(mark.isError || unmark.isError) && (
          <p role="alert" className="rounded-md bg-red-50 p-2 text-sm text-red-700">
            Couldn&apos;t save that tap. Check your connection and try again.
          </p>
        )}
        <p className="text-xs text-rally-subtle">
          Saved as you tap. Tap a green row again to undo it.
          {board.unplaced.length > 0 &&
            ` ${board.unplaced.length} student${board.unplaced.length === 1 ? " isn't" : "s aren't"} on a level yet.`}
        </p>
      </section>
    </div>
  );
}
