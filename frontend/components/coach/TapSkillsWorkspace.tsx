"use client";

import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import {
  markCoachSkillMastered,
  setCoachMasteryNote,
  unmarkCoachSkillMastered,
} from "@/lib/api/coach";
import {
  getCoachSessionSkillBoard,
  type SkillBoardCell,
  type SkillBoardLevelGroup,
} from "@/lib/api/curriculum";
import { fetchAdminAiStatus } from "@/lib/api/admin";
import { NOTE_MAX, criterionFits, pickedCriteria, toggleCriterion } from "@/lib/coach/mastery-note";
import { AI_STATUS_KEY, masteredOn } from "@/lib/coach/progress-narrative";
import { parseAcademyInstant } from "@/lib/format/academy-time";
import { levelSwatch } from "@/lib/level-color";
import { queryKeys } from "@/lib/query/keys";
import { ProgressNarrativeNote } from "@/components/coach/ProgressNarrativeNote";

// Matches the backend's MASTERY_NOTE_WINDOW: notes go on the day's wins.
const NOTE_WINDOW_MS = 24 * 60 * 60 * 1000;

function noteOpen(cell: SkillBoardCell | undefined): boolean {
  if (cell?.status !== "PASSED" || !cell.last_updated_at) return false;
  return Date.now() - parseAcademyInstant(cell.last_updated_at).getTime() < NOTE_WINDOW_MS;
}

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
  // B4: the AI note button shows only when the deployment says AI is on.
  const aiStatus = useQuery({
    queryKey: AI_STATUS_KEY,
    queryFn: fetchAdminAiStatus,
    retry: false,
    staleTime: 5 * 60 * 1000,
  });
  const aiEnabled = aiStatus.data?.enabled === true;
  const [picked, setPicked] = useState<Selection | null>(null);
  const [notice, setNotice] = useState<LevelUpNotice | null>(null);
  const [pendingIds, setPendingIds] = useState<string[]>([]);
  const [noteFor, setNoteFor] = useState<string | null>(null);
  const [draft, setDraft] = useState("");

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

  const saveNote = useMutation({
    mutationFn: (args: { studentId: string; note: string | null }) =>
      setCoachMasteryNote(occurrenceId, args.studentId, skill!.skill_id, args.note, {
        programId,
        date,
      }),
    onSuccess: () => setNoteFor(null),
    onSettled: () => refresh(),
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
            <p className="flex items-center gap-1.5 text-xs font-bold text-status-slate-600">
              <span
                aria-hidden="true"
                className="inline-block h-2.5 w-2.5 rounded-full ring-1 ring-black/25"
                style={{ background: levelSwatch(g.color).fill }}
              />
              {levelLabel(g)}
            </p>
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
            const cell = student.statuses[skill.skill_id];
            const has = cell?.status === "PASSED";
            const note = cell?.coach_note ?? "";
            const noteKey = `${student.student_id}:${skill.skill_id}`;
            const editing = noteFor === noteKey;
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
                        className="block h-full rounded-full"
                        style={{
                          width: `${pct}%`,
                          background: levelSwatch(group.color).fill,
                        }}
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
                {has && noteOpen(cell) && (
                  <MasteryNote
                    studentName={student.student_name}
                    criteria={skill.criteria ?? []}
                    note={note}
                    editing={editing}
                    draft={draft}
                    saving={saveNote.isPending}
                    onDraft={setDraft}
                    onEdit={() => {
                      setDraft(note);
                      setNoteFor(noteKey);
                    }}
                    onCancel={() => setNoteFor(null)}
                    onSave={() =>
                      saveNote.mutate({
                        studentId: student.student_id,
                        note: draft.trim() || null,
                      })
                    }
                    onRemove={() =>
                      saveNote.mutate({
                        studentId: student.student_id,
                        note: null,
                      })
                    }
                  />
                )}
                {aiEnabled && masteredOn(student.statuses, date) && (
                  <ProgressNarrativeNote
                    studentId={student.student_id}
                    studentName={student.student_name}
                    date={date}
                  />
                )}
              </li>
            );
          })}
        </ul>
        {saveNote.isError && (
          <p role="alert" className="rounded-md bg-red-50 p-2 text-sm text-red-700">
            Couldn&apos;t save that note. Try again.
          </p>
        )}
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

/** The optional one-line note to the parent on today's win. */
export function MasteryNote({
  studentName,
  criteria,
  note,
  editing,
  draft,
  saving,
  onDraft,
  onEdit,
  onCancel,
  onSave,
  onRemove,
}: {
  studentName: string;
  /** The skill's criteria: tap to write the note as one templated sentence. */
  criteria: string[];
  note: string;
  editing: boolean;
  draft: string;
  saving: boolean;
  onDraft: (value: string) => void;
  onEdit: () => void;
  onCancel: () => void;
  onSave: () => void;
  onRemove: () => void;
}) {
  if (editing) {
    const inputId = `mastery-note-${studentName.replace(/\W+/g, "-")}`;
    const picked = pickedCriteria(draft, criteria);
    return (
      <div className="mt-1.5 space-y-1.5 px-1">
        <label htmlFor={inputId} className="block text-xs font-bold text-status-slate-600">
          One line for {studentName}&apos;s parents (optional)
        </label>
        {criteria.length > 0 && (
          <div
            role="group"
            aria-label={`Tap what ${studentName} nailed`}
            className="flex flex-wrap gap-1.5"
          >
            {criteria.map((criterion) => {
              const on = picked.includes(criterion);
              return (
                <button
                  key={criterion}
                  type="button"
                  aria-pressed={on}
                  disabled={!criterionFits(draft, criteria, criterion)}
                  onClick={() => onDraft(toggleCriterion(draft, criteria, criterion))}
                  className={`min-h-touch rounded-full border-2 px-3 text-left text-sm font-semibold disabled:opacity-40 ${
                    on
                      ? "border-rally-cobalt bg-rally-cobalt text-white"
                      : "border-rally-line bg-white text-rally-ink"
                  }`}
                >
                  {criterion}
                </button>
              );
            })}
          </div>
        )}
        <input
          id={inputId}
          value={draft}
          maxLength={NOTE_MAX}
          onChange={(e) => onDraft(e.target.value)}
          placeholder="Much quicker to the net this week."
          className="min-h-touch w-full rounded-md border-2 border-rally-line px-3 text-sm"
        />
        <div className="flex items-center justify-between gap-2">
          {/* shortcut: device clock, not the academy timezone; fine while coaches sit in it. */}
          <span className="text-xs text-status-slate-600">
            {draft.length}/{NOTE_MAX} ·{" "}
            {new Date().getHours() < 19
              ? "goes in tonight’s 7 pm email"
              : "tonight’s email has gone; shows on their progress page"}
          </span>
          <span className="flex gap-1.5">
            <button
              type="button"
              onClick={onCancel}
              className="min-h-touch rounded-md border-2 border-rally-line px-3 text-sm font-bold"
            >
              Cancel
            </button>
            <button
              type="button"
              disabled={saving}
              onClick={onSave}
              className="min-h-touch rounded-md bg-rally-cobalt-700 px-3 text-sm font-bold text-white disabled:opacity-50"
            >
              Save note
            </button>
          </span>
        </div>
      </div>
    );
  }
  if (!note) {
    return (
      <button
        type="button"
        onClick={onEdit}
        className="min-h-touch px-1 text-sm font-bold text-rally-cobalt-700"
      >
        + Note for {studentName}&apos;s parents
      </button>
    );
  }
  return (
    <div className="mt-1.5 flex items-center gap-1 rounded-md bg-status-slate-100 py-1 pl-3 pr-1">
      <span className="flex-1 text-sm italic text-status-slate-700">&ldquo;{note}&rdquo;</span>
      <button
        type="button"
        onClick={onEdit}
        aria-label={`Edit the note for ${studentName}'s parents`}
        className="min-h-touch px-2 text-sm font-bold text-rally-cobalt-700"
      >
        Edit
      </button>
      <button
        type="button"
        disabled={saving}
        onClick={onRemove}
        aria-label={`Remove the note for ${studentName}'s parents`}
        className="min-h-touch px-2 text-sm font-bold text-red-700 disabled:opacity-50"
      >
        Remove
      </button>
    </div>
  );
}
