"use client";

import { useState } from "react";
import { X } from "lucide-react";

import type { SkillBoardSkill, SkillStatus } from "@/lib/api/curriculum";

const SETTABLE_STATUSES: { value: SkillStatus; label: string }[] = [
  { value: "INTRODUCED", label: "Introduced" },
  { value: "LEARNING", label: "Learning" },
  { value: "PRACTICING", label: "Practicing" },
  { value: "TEST_READY", label: "Test ready" },
  { value: "NEEDS_REVIEW", label: "Needs review" },
];

export interface SkillCellTarget {
  studentId: string;
  studentName: string;
  skill: SkillBoardSkill;
  levelId: string;
  status: SkillStatus;
}

export function SkillCellEditor({
  target,
  isPending,
  error,
  onSetStatus,
  onQuickPass,
  onRecordTest,
  onClose,
}: {
  target: SkillCellTarget;
  isPending: boolean;
  error: string | null;
  onSetStatus: (status: SkillStatus) => void;
  onQuickPass: () => void;
  onRecordTest: (attempts: number, successes: number, notes: string) => void;
  onClose: () => void;
}) {
  const [showTestForm, setShowTestForm] = useState(false);
  const [attempts, setAttempts] = useState("1");
  const [successes, setSuccesses] = useState("1");
  const [notes, setNotes] = useState("");
  const passed = target.status === "PASSED";

  return (
    <>
      <div
        className="fixed inset-0 z-40 bg-black/30"
        onClick={onClose}
        aria-hidden="true"
      />
      <div
        role="dialog"
        aria-label={`Update ${target.skill.name} for ${target.studentName}`}
        data-testid="skill-cell-editor"
        className="fixed inset-x-0 bottom-0 z-50 rounded-t-2xl border border-neutral-200 bg-white p-4 pb-[max(1rem,env(safe-area-inset-bottom))] shadow-xl sm:inset-x-auto sm:bottom-auto sm:left-1/2 sm:top-1/2 sm:w-[420px] sm:-translate-x-1/2 sm:-translate-y-1/2 sm:rounded-2xl dark:border-neutral-800 dark:bg-neutral-900"
      >
        <div className="mb-3 flex items-start justify-between gap-2">
          <div>
            <p className="text-sm font-semibold text-rally-base">{target.studentName}</p>
            <p className="text-xs text-neutral-500">
              {target.skill.name}
              {target.skill.is_required ? " · required" : ""}
            </p>
          </div>
          <button
            onClick={onClose}
            aria-label="Close"
            className="flex h-11 w-11 items-center justify-center rounded-full text-neutral-400 hover:bg-neutral-100 dark:hover:bg-neutral-800"
          >
            <X className="size-4" aria-hidden="true" />
          </button>
        </div>

        {passed ? (
          <p className="mb-3 rounded-md bg-green-50 p-3 text-sm text-green-700">
            Passed. Record another test to add history.
          </p>
        ) : (
          <div className="mb-3 flex flex-wrap gap-2">
            {SETTABLE_STATUSES.map((s) => (
              <button
                key={s.value}
                disabled={isPending}
                onClick={() => onSetStatus(s.value)}
                className={`min-h-[44px] rounded-full border px-4 text-xs font-medium transition-colors ${
                  target.status === s.value
                    ? "border-blue-600 bg-blue-50 text-blue-700"
                    : "border-neutral-300 text-neutral-600 hover:bg-neutral-50 dark:border-neutral-700 dark:text-neutral-300"
                }`}
              >
                {s.label}
              </button>
            ))}
          </div>
        )}

        <div className="flex gap-2">
          {!passed && (
            <button
              disabled={isPending}
              onClick={onQuickPass}
              data-testid="quick-pass"
              className="min-h-[44px] flex-1 rounded-lg bg-green-600 px-3 text-sm font-semibold text-white transition-all active:scale-95 disabled:opacity-50"
            >
              {isPending ? "Saving…" : "Quick pass (1/1 test)"}
            </button>
          )}
          <button
            disabled={isPending}
            onClick={() => setShowTestForm((v) => !v)}
            className="min-h-[44px] flex-1 rounded-lg border border-neutral-300 px-3 text-sm font-medium text-neutral-700 dark:border-neutral-700 dark:text-neutral-300"
          >
            {showTestForm ? "Cancel test" : "Record test…"}
          </button>
        </div>

        {showTestForm && (
          <div className="mt-3 rounded-lg bg-neutral-50 p-3 dark:bg-neutral-800">
            <div className="grid grid-cols-2 gap-2">
              <label className="block">
                <span className="mb-1 block text-[11px] font-medium text-neutral-500">
                  Attempts
                </span>
                <input
                  type="number"
                  min="1"
                  inputMode="numeric"
                  value={attempts}
                  onChange={(e) => setAttempts(e.target.value)}
                  className="min-h-[44px] w-full rounded-md border border-neutral-300 px-2 text-sm"
                />
              </label>
              <label className="block">
                <span className="mb-1 block text-[11px] font-medium text-neutral-500">
                  Successes
                </span>
                <input
                  type="number"
                  min="0"
                  inputMode="numeric"
                  value={successes}
                  onChange={(e) => setSuccesses(e.target.value)}
                  className="min-h-[44px] w-full rounded-md border border-neutral-300 px-2 text-sm"
                />
              </label>
            </div>
            <label className="mt-2 block">
              <span className="mb-1 block text-[11px] font-medium text-neutral-500">
                Notes (optional)
              </span>
              <input
                type="text"
                value={notes}
                onChange={(e) => setNotes(e.target.value)}
                className="min-h-[44px] w-full rounded-md border border-neutral-300 px-2 text-sm"
              />
            </label>
            <button
              disabled={isPending}
              onClick={() =>
                onRecordTest(
                  parseInt(attempts, 10) || 1,
                  parseInt(successes, 10) || 0,
                  notes.trim(),
                )
              }
              className="mt-3 min-h-[44px] w-full rounded-lg bg-blue-600 text-sm font-semibold text-white active:scale-95 disabled:opacity-50"
            >
              Save test
            </button>
          </div>
        )}

        {error && <p className="mt-2 text-xs text-red-600">{error}</p>}
      </div>
    </>
  );
}
