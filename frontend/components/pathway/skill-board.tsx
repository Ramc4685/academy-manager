"use client";

import { useState } from "react";

import type {
  SkillBoard,
  SkillBoardLevelGroup,
  SkillBoardSkill,
  SkillBoardStudentRow,
  SkillStatus,
} from "@/lib/api/curriculum";
import { SkillCellEditor, type SkillCellTarget } from "./skill-cell-editor";

export interface SkillBoardActions {
  setStatus: (args: {
    studentId: string;
    skillId: string;
    levelId: string;
    status: SkillStatus;
  }) => Promise<unknown>;
  quickPass: (args: {
    studentId: string;
    skillId: string;
    levelId: string;
  }) => Promise<unknown>;
  recordTest: (args: {
    studentId: string;
    skillId: string;
    levelId: string;
    attempts: number;
    successes: number;
    notes: string;
  }) => Promise<unknown>;
}

const STATUS_DOT: Record<SkillStatus, string> = {
  NOT_STARTED: "border-2 border-neutral-300 bg-transparent",
  INTRODUCED: "bg-neutral-400",
  LEARNING: "bg-amber-400",
  PRACTICING: "bg-amber-500",
  TEST_READY: "bg-blue-500",
  PASSED: "bg-green-500",
  NEEDS_REVIEW: "bg-red-500",
};

const STATUS_SHORT: Record<SkillStatus, string> = {
  NOT_STARTED: "Not started",
  INTRODUCED: "Introduced",
  LEARNING: "Learning",
  PRACTICING: "Practicing",
  TEST_READY: "Test ready",
  PASSED: "Passed",
  NEEDS_REVIEW: "Needs review",
};

export function SkillBoardView({
  board,
  actions,
  renderUnplacedAction,
}: {
  board: SkillBoard;
  actions: SkillBoardActions;
  renderUnplacedAction?: (student: {
    student_id: string;
    student_name: string;
  }) => React.ReactNode;
}) {
  const [target, setTarget] = useState<SkillCellTarget | null>(null);
  const [isPending, setIsPending] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function run(fn: () => Promise<unknown>) {
    setIsPending(true);
    setError(null);
    try {
      await fn();
      setTarget(null);
    } catch {
      setError("Update failed. Check connection and retry.");
    } finally {
      setIsPending(false);
    }
  }

  return (
    <div className="space-y-6" data-testid="skill-board">
      {board.groups.length === 0 && board.unplaced.length === 0 && (
        <p className="text-sm text-neutral-500">No students on this roster.</p>
      )}

      {board.groups.map((group) => (
        <LevelGroupSection
          key={group.level_id}
          group={group}
          onCellTap={(student, skill) =>
            setTarget({
              studentId: student.student_id,
              studentName: student.student_name,
              skill,
              levelId: group.level_id,
              status: student.statuses[skill.skill_id]?.status ?? "NOT_STARTED",
            })
          }
        />
      ))}

      {board.unplaced.length > 0 && (
        <div className="rounded-xl border border-dashed border-neutral-300 p-4 dark:border-neutral-700">
          <p className="mb-2 text-sm font-semibold text-neutral-600">Not placed in a level</p>
          <ul className="space-y-2">
            {board.unplaced.map((s) => (
              <li
                key={s.student_id}
                className="flex items-center justify-between gap-2 text-sm"
              >
                <span>{s.student_name}</span>
                {renderUnplacedAction?.(s)}
              </li>
            ))}
          </ul>
        </div>
      )}

      {target && (
        <SkillCellEditor
          target={target}
          isPending={isPending}
          error={error}
          onClose={() => setTarget(null)}
          onSetStatus={(status) =>
            run(() =>
              actions.setStatus({
                studentId: target.studentId,
                skillId: target.skill.skill_id,
                levelId: target.levelId,
                status,
              }),
            )
          }
          onQuickPass={() =>
            run(() =>
              actions.quickPass({
                studentId: target.studentId,
                skillId: target.skill.skill_id,
                levelId: target.levelId,
              }),
            )
          }
          onRecordTest={(attempts, successes, notes) =>
            run(() =>
              actions.recordTest({
                studentId: target.studentId,
                skillId: target.skill.skill_id,
                levelId: target.levelId,
                attempts,
                successes,
                notes,
              }),
            )
          }
        />
      )}
    </div>
  );
}

function LevelGroupSection({
  group,
  onCellTap,
}: {
  group: SkillBoardLevelGroup;
  onCellTap: (student: SkillBoardStudentRow, skill: SkillBoardSkill) => void;
}) {
  const [mode, setMode] = useState<"by-student" | "by-skill">("by-student");
  const [skillId, setSkillId] = useState(group.skills[0]?.skill_id ?? "");
  const activeSkill =
    group.skills.find((s) => s.skill_id === skillId) ?? group.skills[0];

  return (
    <section data-testid={`skill-board-level-${group.sequence}`}>
      <h2 className="mb-2 text-sm font-semibold text-rally-base">
        Level {group.sequence} · {group.level_name}
      </h2>

      {/* Desktop matrix */}
      <div className="hidden overflow-x-auto rounded-xl border border-neutral-200 bg-white md:block dark:border-neutral-800 dark:bg-neutral-900">
        <table className="w-full text-xs">
          <thead>
            <tr className="border-b border-neutral-200 text-neutral-500 dark:border-neutral-800">
              <th className="px-3 py-2 text-left font-medium">Student</th>
              {group.skills.map((skill) => (
                <th key={skill.skill_id} className="px-1 py-2 text-center font-medium">
                  <span title={skill.name}>{skill.name}</span>
                  {skill.is_required && <span className="text-red-500"> *</span>}
                </th>
              ))}
              <th className="px-2 py-2 text-center font-medium">Done</th>
            </tr>
          </thead>
          <tbody>
            {group.students.map((student) => (
              <tr
                key={student.student_id}
                className="border-b border-neutral-100 last:border-0 dark:border-neutral-800"
              >
                <td className="px-3 py-2 font-medium">
                  {student.student_name}
                  {student.required_passed === student.required_total &&
                    student.required_total > 0 && (
                      <span className="ml-2 rounded-full bg-green-100 px-2 py-0.5 text-[10px] font-semibold text-green-700">
                        Ready
                      </span>
                    )}
                </td>
                {group.skills.map((skill) => {
                  const status = student.statuses[skill.skill_id]?.status ?? "NOT_STARTED";
                  return (
                    <td key={skill.skill_id} className="px-1 py-1 text-center">
                      <button
                        aria-label={`${student.student_name} – ${skill.name}: ${STATUS_SHORT[status]}`}
                        onClick={() => onCellTap(student, skill)}
                        className="inline-flex h-9 w-9 items-center justify-center rounded-md hover:bg-neutral-100 dark:hover:bg-neutral-800"
                      >
                        <span className={`h-3.5 w-3.5 rounded-full ${STATUS_DOT[status]}`} />
                      </button>
                    </td>
                  );
                })}
                <td className="px-2 py-2 text-center text-neutral-500">
                  {student.total_passed}/{student.total_count}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      {/* Mobile modes */}
      <div className="md:hidden">
        <div className="mb-3 grid grid-cols-2 gap-1 rounded-lg bg-neutral-100 p-1 dark:bg-neutral-800">
          {(["by-student", "by-skill"] as const).map((m) => (
            <button
              key={m}
              onClick={() => setMode(m)}
              className={`min-h-[44px] rounded-md text-xs font-semibold ${
                mode === m
                  ? "bg-white text-rally-base shadow-sm dark:bg-neutral-700"
                  : "text-neutral-500"
              }`}
            >
              {m === "by-student" ? "By student" : "By skill"}
            </button>
          ))}
        </div>

        {mode === "by-student" ? (
          <ul className="space-y-2">
            {group.students.map((student) => (
              <li
                key={student.student_id}
                data-testid={`skill-card-${student.student_id}`}
                className="rounded-xl border border-neutral-200 bg-white p-3 dark:border-neutral-800 dark:bg-neutral-900"
              >
                <div className="mb-2 flex items-center justify-between">
                  <p className="text-sm font-semibold">{student.student_name}</p>
                  <p className="text-xs text-neutral-500">
                    {student.total_passed}/{student.total_count} passed
                  </p>
                </div>
                <div className="flex flex-wrap gap-1.5">
                  {group.skills.map((skill) => {
                    const status = student.statuses[skill.skill_id]?.status ?? "NOT_STARTED";
                    return (
                      <button
                        key={skill.skill_id}
                        onClick={() => onCellTap(student, skill)}
                        className="flex min-h-[44px] items-center gap-1.5 rounded-full border border-neutral-200 px-3 text-[11px] font-medium dark:border-neutral-700"
                      >
                        <span className={`h-2.5 w-2.5 rounded-full ${STATUS_DOT[status]}`} />
                        {skill.name}
                      </button>
                    );
                  })}
                </div>
              </li>
            ))}
          </ul>
        ) : (
          <div>
            <select
              value={activeSkill?.skill_id ?? ""}
              onChange={(e) => setSkillId(e.target.value)}
              aria-label="Skill to assess"
              className="mb-3 h-11 min-h-[44px] w-full rounded-lg border border-neutral-300 px-3 text-sm dark:border-neutral-700 dark:bg-neutral-900"
            >
              {group.skills.map((skill) => (
                <option key={skill.skill_id} value={skill.skill_id}>
                  {skill.sequence}. {skill.name}
                  {skill.is_required ? " (required)" : ""}
                </option>
              ))}
            </select>
            <ul className="space-y-2">
              {activeSkill &&
                group.students.map((student) => {
                  const status =
                    student.statuses[activeSkill.skill_id]?.status ?? "NOT_STARTED";
                  return (
                    <li key={student.student_id}>
                      <button
                        onClick={() => onCellTap(student, activeSkill)}
                        data-testid={`by-skill-student-${student.student_id}`}
                        className="flex min-h-[52px] w-full items-center justify-between rounded-xl border border-neutral-200 bg-white px-4 dark:border-neutral-800 dark:bg-neutral-900"
                      >
                        <span className="text-sm font-semibold">{student.student_name}</span>
                        <span className="flex items-center gap-2 text-xs text-neutral-500">
                          <span className={`h-3 w-3 rounded-full ${STATUS_DOT[status]}`} />
                          {STATUS_SHORT[status]}
                        </span>
                      </button>
                    </li>
                  );
                })}
            </ul>
          </div>
        )}
      </div>
    </section>
  );
}
