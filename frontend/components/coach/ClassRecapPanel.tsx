"use client";

import { useEffect, useRef, useState } from "react";
import Link from "next/link";
import {
  useMutation,
  useQuery,
  useQueryClient,
  type QueryClient,
} from "@tanstack/react-query";

import { Button } from "@/components/ds/button";
import type { ApiError } from "@/lib/api/client";
import {
  getClassRecap,
  resolveClassReport,
  saveClassRecap,
  submitClassReport,
  type ChildPractice,
  type ClassPass,
  type ClassRecapView,
  type GroupLesson,
  type PassReceipt,
  type ClassReport,
} from "@/lib/api/class-recap";
import {
  creditEveryone,
  lessonsWithoutSkill,
  nextReportAttempt,
  practiceEligible,
  reportOutcomeLabel,
  toggleGroupSkill,
  togglePractice,
  withoutSkill,
  type ReportAttempt,
} from "@/lib/coach/class-recap";
import { queryKeys } from "@/lib/query/keys";

interface Draft {
  taught: string[];
  practice: ChildPractice[];
  passes: ClassPass[];
  lessons: GroupLesson[];
}

const RECEIPT: Record<PassReceipt, string> = {
  recorded: "Pass recorded",
  counted: "Counted as a try; not passed yet",
  in_progress: "Pass still saving. Save again to finish it.",
  earned_before: "Already passed before this class",
  not_recorded: "Not counted by the skill rules",
};

function viewDraft(view: ClassRecapView): Draft {
  return {
    taught: view.taught_skills.map((s) => s.skill_id),
    practice: view.practice,
    passes: (view.passes ?? []).map(({ student_id, skill_id }) => ({
      student_id,
      skill_id,
    })),
    lessons: view.group_lessons ?? [],
  };
}

function saveError(err: unknown): string {
  const e = err as ApiError;
  if (e?.status === 409) {
    return "This recap changed since you opened it. The latest version is loaded; check it and save again.";
  }
  return e?.message || "Could not save the recap.";
}

/**
 * A failed report send. A 409 while the first send is still reading the
 * report keeps its id, so the retry replays it instead of starting a second
 * read; any other 409 means the id is spent and the next send mints a new one.
 */
/** Today's recap shortcut reads `recap_saved` from every cached Today list. */
export function refreshTodayRecapFlags(queryClient: QueryClient): void {
  void queryClient.invalidateQueries({ queryKey: ["coach", "today"] });
}

export function afterReportError(
  err: unknown,
  last: ReportAttempt | null,
): { attempt: ReportAttempt | null; message: string } {
  const e = err as ApiError;
  if (e?.status === 409 && e.details?.processing === true) {
    return {
      attempt: last,
      message:
        "Your report is still being read. Wait a moment, then send it again.",
    };
  }
  return {
    attempt: e?.status === 409 ? null : last,
    message: e?.message || "Could not send the report.",
  };
}

/**
 * One dated class's shared recap: taught skills, and per child which skills
 * they actually practised. The assigned lead coach and the owner edit it;
 * assistants and admins read it. Teaching a skill never credits a child.
 */
export function ClassRecapPanel({
  occurrenceId,
  skillsHref,
}: {
  occurrenceId: string;
  skillsHref?: string;
}) {
  const query = useQuery({
    queryKey: queryKeys.classRecap.occurrence(occurrenceId),
    queryFn: () => getClassRecap(occurrenceId),
  });

  if (query.isLoading) {
    return (
      <p className="text-sm text-rally-subtle">Loading the class recap…</p>
    );
  }
  if (query.isError || !query.data) {
    return (
      <p role="alert" className="text-sm text-rally-ink">
        Could not load the class recap.{" "}
        <button
          type="button"
          className="underline"
          onClick={() => void query.refetch()}
        >
          Try again
        </button>
      </p>
    );
  }
  return <ClassRecapEditor view={query.data} skillsHref={skillsHref} />;
}

export function ClassRecapEditor({
  view,
  skillsHref,
}: {
  view: ClassRecapView;
  skillsHref?: string;
}) {
  const [recapDirty, setRecapDirty] = useState(false);
  return (
    <div className="space-y-5">
      {/* Keyed by revision: a save or a report that changed the recap resets the draft. */}
      <ClassRecapBody
        key={view.revision}
        view={view}
        skillsHref={skillsHref}
        onDirtyChange={setRecapDirty}
      />
      {/* Outside the keyed body, so a report's result survives the revision it causes. */}
      {view.can_edit && <ClassReportForm view={view} recapDirty={recapDirty} />}
    </div>
  );
}

export function ClassRecapBody({
  view,
  skillsHref,
  onDirtyChange,
}: {
  view: ClassRecapView;
  /** The class's skills page, where a report's pass claim is signed off. */
  skillsHref?: string;
  onDirtyChange?: (dirty: boolean) => void;
}) {
  const queryClient = useQueryClient();
  const key = queryKeys.classRecap.occurrence(view.occurrence_id);
  const [draft, setDraft] = useState<Draft>(() => viewDraft(view));
  const [picked, setPicked] = useState("");
  // "" means every taught skill.
  const [creditSkill, setCreditSkill] = useState("");
  const [error, setError] = useState<string | null>(null);

  const names = new Map(
    [...view.skill_options, ...view.taught_skills].map((s) => [
      s.skill_id,
      s.name,
    ]),
  );
  const eligible = practiceEligible(view.roster);
  const saved = new Map(
    (view.passes ?? []).map((p) => [`${p.student_id}:${p.skill_id}`, p]),
  );
  // A save that stopped part way is finished by saving again.
  const unfinished = (view.passes ?? []).some((p) => p.receipt === "in_progress");
  const dirty = JSON.stringify(draft) !== JSON.stringify(viewDraft(view));

  useEffect(() => onDirtyChange?.(dirty), [dirty, onDirtyChange]);

  const save = useMutation({
    mutationFn: () =>
      saveClassRecap(view.occurrence_id, {
        class_starts_at: view.class_starts_at,
        mutation_id: crypto.randomUUID(),
        expected_revision: view.revision,
        taught_skill_ids: draft.taught,
        practice: draft.practice,
        passes: draft.passes,
        group_lessons: draft.lessons,
      }),
    onSuccess: (next) => {
      setError(null);
      queryClient.setQueryData(key, next);
      refreshTodayRecapFlags(queryClient);
    },
    onError: (err) => {
      setError(saveError(err));
      void queryClient.invalidateQueries({ queryKey: key });
    },
  });

  const practised = (studentId: string) =>
    draft.practice.find((p) => p.student_id === studentId)?.skill_ids ?? [];
  const passed = (studentId: string, skillId: string) =>
    draft.passes.some((p) => p.student_id === studentId && p.skill_id === skillId);
  const togglePass = (studentId: string, skillId: string) =>
    setDraft((d) => ({
      ...d,
      passes: passed(studentId, skillId)
        ? d.passes.filter((p) => !(p.student_id === studentId && p.skill_id === skillId))
        : [...d.passes, { student_id: studentId, skill_id: skillId }],
    }));

  return (
    <div className="space-y-5" data-testid="class-recap">
      <section aria-labelledby="recap-taught">
        <h3 id="recap-taught" className="text-sm font-semibold text-rally-ink">
          Taught in this class
        </h3>
        {draft.taught.length === 0 ? (
          <p className="mt-1 text-sm text-rally-subtle">
            No skills recorded yet.
          </p>
        ) : (
          <ul
            className="mt-2 flex flex-wrap gap-2"
            data-testid="recap-taught-list"
          >
            {draft.taught.map((id) => (
              <li
                key={id}
                className="inline-flex items-center gap-1 rounded-full border border-rally-line px-3 py-1 text-sm text-rally-ink"
              >
                {names.get(id) ?? "Retired skill"}
                {view.can_edit && (
                  <button
                    type="button"
                    aria-label={`Remove ${names.get(id) ?? "skill"}`}
                    className="min-h-touch px-1 text-rally-muted"
                    onClick={() =>
                      setDraft((d) => ({
                        taught: d.taught.filter((t) => t !== id),
                        practice: withoutSkill(d.practice, id),
                        lessons: lessonsWithoutSkill(d.lessons, id),
                        // Saved passes stand; only unsaved ones go with the skill.
                        passes: d.passes.filter(
                          (p) =>
                            p.skill_id !== id ||
                            saved.has(`${p.student_id}:${p.skill_id}`),
                        ),
                      }))
                    }
                  >
                    ×
                  </button>
                )}
              </li>
            ))}
          </ul>
        )}
        {view.can_edit && (
          <div className="mt-2 flex gap-2">
            <label
              className="sr-only"
              htmlFor={`recap-skill-${view.occurrence_id}`}
            >
              Add a taught skill
            </label>
            <select
              id={`recap-skill-${view.occurrence_id}`}
              data-testid="recap-skill-select"
              value={picked}
              onChange={(e) => setPicked(e.target.value)}
              className="min-h-touch min-w-0 flex-1 rounded-md border border-rally-line px-2 text-sm"
            >
              <option value="">Choose a skill (any level)…</option>
              {view.skill_options
                .filter((s) => !draft.taught.includes(s.skill_id))
                .map((s) => (
                  <option key={s.skill_id} value={s.skill_id}>
                    {s.level_name ? `${s.level_name} · ${s.name}` : s.name}
                  </option>
                ))}
            </select>
            <Button
              variant="secondary"
              size="sm"
              disabled={!picked}
              onClick={() => {
                setDraft((d) => ({ ...d, taught: [...d.taught, picked] }));
                setPicked("");
              }}
            >
              Add
            </Button>
          </div>
        )}
      </section>

      <GroupLessons
        view={view}
        taught={draft.taught}
        lessons={draft.lessons}
        names={names}
        onToggle={(levelId, skillId) =>
          setDraft((d) => ({
            ...d,
            lessons: toggleGroupSkill(d.lessons, levelId, skillId),
          }))
        }
      />

      <section aria-labelledby="recap-practice">
        <h3
          id="recap-practice"
          className="text-sm font-semibold text-rally-ink"
        >
          Who practised what
        </h3>
        <p className="mt-1 text-xs text-rally-subtle">
          Only children marked present or late can be credited. Teaching a skill
          does not mark anyone as having practised it.
        </p>
        {eligible.length === 0 ? (
          <p className="mt-2 text-sm text-rally-subtle">
            No one is marked present yet. Mark attendance first.
          </p>
        ) : draft.taught.length === 0 ? (
          <p className="mt-2 text-sm text-rally-subtle">
            Add a taught skill first.
          </p>
        ) : (
          <>
            {view.can_edit && (
              <div className="mt-2 flex gap-2">
                <label
                  className="sr-only"
                  htmlFor={`recap-credit-${view.occurrence_id}`}
                >
                  Skill to credit to everyone present
                </label>
                <select
                  id={`recap-credit-${view.occurrence_id}`}
                  data-testid="recap-credit-select"
                  value={draft.taught.includes(creditSkill) ? creditSkill : ""}
                  onChange={(e) => setCreditSkill(e.target.value)}
                  className="min-h-touch min-w-0 flex-1 rounded-md border border-rally-line px-2 text-sm"
                >
                  <option value="">All taught skills</option>
                  {draft.taught.map((id) => (
                    <option key={id} value={id}>
                      {names.get(id) ?? "Retired skill"}
                    </option>
                  ))}
                </select>
                <Button
                  variant="secondary"
                  size="sm"
                  data-testid="recap-credit-everyone"
                  onClick={() =>
                    setDraft((d) => ({
                      ...d,
                      practice: creditEveryone(
                        d.practice,
                        view.roster,
                        d.taught.includes(creditSkill)
                          ? [creditSkill]
                          : d.taught,
                      ),
                    }))
                  }
                >
                  {`Credit everyone present (${eligible.length})`}
                </Button>
              </div>
            )}
            <ul
              className="mt-2 divide-y divide-rally-line"
              data-testid="recap-practice-grid"
            >
              {eligible.map((child) => (
                <li key={child.student_id} className="py-2">
                  <p className="text-sm font-medium text-rally-ink">
                    {child.name}
                  </p>
                  <div className="mt-1 flex flex-wrap gap-2">
                    {draft.taught.map((skillId) => {
                      const on = practised(child.student_id).includes(skillId);
                      const label = names.get(skillId) ?? "Retired skill";
                      return view.can_edit ? (
                        <button
                          key={skillId}
                          type="button"
                          aria-pressed={on}
                          data-testid={`practice-${child.student_id}-${skillId}`}
                          onClick={() =>
                            setDraft((d) => ({
                              ...d,
                              practice: togglePractice(
                                d.practice,
                                child.student_id,
                                skillId,
                              ),
                            }))
                          }
                          className={`min-h-touch rounded-full border px-3 text-sm ${
                            on
                              ? "border-rally-ink bg-rally-ink text-white"
                              : "border-rally-line text-rally-muted"
                          }`}
                        >
                          {on ? "✓ " : ""}
                          {label}
                        </button>
                      ) : on ? (
                        <span
                          key={skillId}
                          className="rounded-full border border-rally-line px-3 py-1 text-sm text-rally-ink"
                        >
                          {label}
                        </span>
                      ) : null;
                    })}
                  </div>
                  <PassRow
                    studentId={child.student_id}
                    skills={draft.taught}
                    names={names}
                    canEdit={view.can_edit}
                    isPassed={passed}
                    saved={saved}
                    onToggle={togglePass}
                  />
                </li>
              ))}
            </ul>
          </>
        )}
      </section>

      {error && (
        <p role="alert" className="text-sm text-rally-ink">
          {error}
        </p>
      )}
      {view.can_edit && (
        <Button
          variant="primary"
          disabled={!(dirty || unfinished) || save.isPending}
          onClick={() => save.mutate()}
          data-testid="recap-save"
        >
          {save.isPending ? "Saving…" : unfinished ? "Finish saving" : "Save recap"}
        </Button>
      )}
      {/* Testers could not tell whether a recap had saved (usability study). */}
      {view.can_edit && !save.isPending && (
        <p role="status" data-testid="recap-save-state" className="text-xs text-rally-subtle">
          {dirty ? "Unsaved changes." : view.revision > 0 ? "Recap saved." : "No recap saved yet."}
        </p>
      )}
      {!view.can_edit && (
        <p className="text-xs text-rally-subtle" data-testid="recap-read-only">
          Only the class&apos;s lead coach or the owner can change this recap.
        </p>
      )}

      {view.reports.length > 0 && (
        <ReportList
          view={view}
          names={names}
          skillsHref={skillsHref}
          // A reported pass is only a claim: the editor adds it here and the
          // recap save runs it through the pass rules, like a tapped pass.
          canAddPass={(studentId, skillId) =>
            view.can_edit &&
            draft.taught.includes(skillId) &&
            eligible.some((c) => c.student_id === studentId) &&
            !passed(studentId, skillId)
          }
          onAddPass={togglePass}
        />
      )}
    </div>
  );
}

/** What each level group worked on. The next class's teaching plan reads
 * it to pick each group a drill it did not just do. Editors only: the
 * server sends groups to the lead coach and the owner. */
function GroupLessons({
  view,
  taught,
  lessons,
  names,
  onToggle,
}: {
  view: ClassRecapView;
  taught: string[];
  lessons: GroupLesson[];
  names: Map<string, string>;
  onToggle: (levelId: string, skillId: string) => void;
}) {
  const groups = view.groups ?? [];
  if (!view.can_edit || groups.length === 0 || taught.length === 0) return null;
  const studentName = new Map(view.roster.map((r) => [r.student_id, r.name]));
  const worked = (levelId: string) =>
    lessons.find((l) => l.level_id === levelId)?.skill_ids ?? [];
  return (
    <section aria-labelledby="recap-groups" data-testid="recap-groups">
      <h3 id="recap-groups" className="text-sm font-semibold text-rally-ink">
        What each group worked on
      </h3>
      <p className="mt-1 text-xs text-rally-subtle">
        The next class&apos;s plan uses this to give each group a drill it did
        not just do.
      </p>
      <ul className="mt-2 divide-y divide-rally-line">
        {groups.map((group) => {
          const done = worked(group.level_id);
          const members = group.student_ids
            .map((id) => studentName.get(id))
            .filter(Boolean)
            .join(", ");
          return (
            <li
              key={group.level_id}
              className="py-2"
              data-testid={`recap-group-${group.level_id}`}
            >
              <p className="text-sm font-medium text-rally-ink">{group.name}</p>
              {members && (
                <p className="text-xs text-rally-subtle">{members}</p>
              )}
              <div className="mt-1 flex flex-wrap gap-2">
                {taught.map((skillId) => {
                  const on = done.includes(skillId);
                  const label = names.get(skillId) ?? "Retired skill";
                  return (
                    <button
                      key={skillId}
                      type="button"
                      aria-pressed={on}
                      aria-label={`${group.name} worked on ${label}`}
                      data-testid={`group-${group.level_id}-${skillId}`}
                      onClick={() => onToggle(group.level_id, skillId)}
                      className={`min-h-touch rounded-full border px-3 text-sm ${
                        on
                          ? "border-rally-ink bg-rally-ink text-white"
                          : "border-rally-line text-rally-muted"
                      }`}
                    >
                      {on ? "✓ " : ""}
                      {label}
                    </button>
                  );
                })}
              </div>
            </li>
          );
        })}
      </ul>
    </section>
  );
}

/** Skills this child passed at this class. A saved pass is locked: taking
 * it back is a formal reassessment, not a recap edit. */
function PassRow({
  studentId,
  skills,
  names,
  canEdit,
  isPassed,
  saved,
  onToggle,
}: {
  studentId: string;
  skills: string[];
  names: Map<string, string>;
  canEdit: boolean;
  isPassed: (studentId: string, skillId: string) => boolean;
  saved: Map<string, { receipt: PassReceipt }>;
  onToggle: (studentId: string, skillId: string) => void;
}) {
  const rows = skills.filter(
    (id) => canEdit || isPassed(studentId, id),
  );
  if (rows.length === 0) return null;
  return (
    <div className="mt-2" data-testid={`passes-${studentId}`}>
      <p className="text-xs text-rally-subtle">Passed at this class</p>
      <ul className="mt-1 space-y-1">
        {rows.map((skillId) => {
          const on = isPassed(studentId, skillId);
          const kept = saved.get(`${studentId}:${skillId}`);
          const label = names.get(skillId) ?? "Retired skill";
          return (
            <li key={skillId} className="flex flex-wrap items-center gap-2">
              {/* Only a pass the skill rules never counted can be taken off. */}
              {canEdit && (!kept || kept.receipt === "not_recorded") ? (
                <button
                  type="button"
                  aria-pressed={on}
                  data-testid={`pass-${studentId}-${skillId}`}
                  onClick={() => onToggle(studentId, skillId)}
                  className={`min-h-touch rounded-full border px-3 text-sm ${
                    on
                      ? "border-rally-ink bg-rally-ink text-white"
                      : "border-dashed border-rally-line text-rally-muted"
                  }`}
                >
                  {on ? "✓ Passed: " : "Passed: "}
                  {label}
                </button>
              ) : (
                on && (
                  <span className="rounded-full border border-rally-ink px-3 py-1 text-sm text-rally-ink">
                    {`✓ Passed: ${label}`}
                  </span>
                )
              )}
              {kept && (
                <span
                  className="text-xs text-rally-subtle"
                  data-testid={`pass-receipt-${studentId}-${skillId}`}
                >
                  {RECEIPT[kept.receipt]}
                </span>
              )}
            </li>
          );
        })}
      </ul>
    </div>
  );
}

export function ClassReportForm({
  view,
  recapDirty = false,
}: {
  view: ClassRecapView;
  /** Unsaved recap edits: an applied report would reload the recap over them. */
  recapDirty?: boolean;
}) {
  const queryClient = useQueryClient();
  const [text, setText] = useState("");
  const [useAi, setUseAi] = useState(false);
  // The last unanswered send: a retry of the same report replays its id.
  const attempt = useRef<ReportAttempt | null>(null);
  const [result, setResult] = useState<ClassReport | null>(null);
  const [error, setError] = useState<string | null>(null);
  const id = `recap-report-${view.occurrence_id}`;

  const submit = useMutation({
    mutationFn: () => {
      const next = nextReportAttempt(
        attempt.current,
        text.trim(),
        view.ai_enabled && useAi,
        () => crypto.randomUUID(),
      );
      attempt.current = next;
      return submitClassReport(view.occurrence_id, {
        class_starts_at: view.class_starts_at,
        report_id: next.reportId,
        text: next.text,
        use_ai: next.useAi,
      });
    },
    onSuccess: (report) => {
      attempt.current = null;
      setResult(report);
      setError(null);
      setText("");
      void queryClient.invalidateQueries({
        queryKey: queryKeys.classRecap.occurrence(view.occurrence_id),
      });
      refreshTodayRecapFlags(queryClient);
    },
    onError: (err) => {
      const next = afterReportError(err, attempt.current);
      attempt.current = next.attempt;
      setError(next.message);
    },
  });

  return (
    <section
      aria-labelledby={`${id}-title`}
      className="rounded-lg border border-rally-line p-3"
    >
      <h3 id={`${id}-title`} className="text-sm font-semibold text-rally-ink">
        After-class report
      </h3>
      <p className="mt-1 text-xs text-rally-subtle">
        Describe what the class worked on and who practised what. Name the
        children who took part, or say &quot;everyone&quot;. A report only adds
        to the recap; it never removes anything.
      </p>
      <label htmlFor={id} className="sr-only">
        After-class report
      </label>
      <textarea
        id={id}
        data-testid="recap-report-text"
        value={text}
        maxLength={2000}
        rows={4}
        onChange={(e) => setText(e.target.value)}
        className="mt-2 w-full rounded-md border border-rally-line p-2 text-sm"
      />
      {view.ai_enabled ? (
        // Optional AI reading sits behind a disclosure: the standard report is
        // the whole job, and the consent text is long.
        <details
          className="mt-2 rounded-md bg-rally-paper p-2"
          data-testid="recap-ai-options"
        >
          <summary className="min-h-touch cursor-pointer content-center text-sm font-medium text-rally-ink">
            More options: AI reading
          </summary>
          <label className="mt-2 flex items-start gap-2 text-sm text-rally-ink">
            <input
              type="checkbox"
              data-testid="recap-report-use-ai"
              checked={useAi}
              onChange={(e) => setUseAi(e.target.checked)}
              className="mt-1"
              aria-describedby={`${id}-ai-note`}
            />
            Let AI read this report (optional)
          </label>
          <p
            id={`${id}-ai-note`}
            className="mt-1 text-xs text-rally-muted"
            data-testid="recap-ai-note"
          >
            If you tick this, the report goes to the academy&apos;s AI provider
            with children&apos;s names swapped for codes and emails and phone
            numbers removed. Skills and practice it can match to your words are
            added straight to the recap; anything unclear comes back to you as a
            question. Passes are never recorded from a report. Leave it unticked
            and the report goes to the owner, who enters it by hand.
          </p>
        </details>
      ) : (
        <p
          className="mt-2 text-xs text-rally-muted"
          data-testid="recap-ai-off-note"
        >
          This report goes to the owner, who adds it to the recap by hand.
        </p>
      )}
      {error && (
        <p role="alert" className="mt-2 text-sm text-rally-ink">
          {error}
        </p>
      )}
      {recapDirty && (
        <p
          className="mt-2 text-sm text-rally-ink"
          data-testid="recap-report-blocked"
        >
          Save or undo your recap changes first. A report updates the recap and
          would replace unsaved edits.
        </p>
      )}
      {result && (
        <p
          role="status"
          className="mt-2 text-sm text-rally-ink"
          data-testid="recap-report-result"
        >
          {reportOutcomeLabel(result.outcome)}
          {result.questions.length > 0
            ? `: ${result.questions.join(" ")}`
            : "."}
        </p>
      )}
      <div className="mt-2">
        <Button
          variant="secondary"
          disabled={!text.trim() || submit.isPending || recapDirty}
          onClick={() => submit.mutate()}
          data-testid="recap-report-submit"
        >
          {submit.isPending
            ? "Sending…"
            : view.ai_enabled && useAi
              ? "Send and read with AI"
              : "Send to owner"}
        </Button>
      </div>
    </section>
  );
}

function ReportList({
  view,
  names,
  skillsHref,
  canAddPass,
  onAddPass,
}: {
  view: ClassRecapView;
  names: Map<string, string>;
  skillsHref?: string;
  canAddPass: (studentId: string, skillId: string) => boolean;
  onAddPass: (studentId: string, skillId: string) => void;
}) {
  const queryClient = useQueryClient();
  const studentName = new Map(view.roster.map((r) => [r.student_id, r.name]));
  const resolve = useMutation({
    mutationFn: (reportId: string) =>
      resolveClassReport(view.occurrence_id, reportId),
    onSuccess: () => {
      void queryClient.invalidateQueries({
        queryKey: queryKeys.classRecap.occurrence(view.occurrence_id),
      });
      void queryClient.invalidateQueries({
        queryKey: queryKeys.classRecap.handoffs(),
      });
    },
  });

  return (
    <section aria-labelledby={`recap-reports-${view.occurrence_id}`}>
      <h3
        id={`recap-reports-${view.occurrence_id}`}
        className="text-sm font-semibold text-rally-ink"
      >
        {view.can_resolve ? "Reports for this class" : "Your reports"}
      </h3>
      <ul className="mt-2 space-y-2" data-testid="recap-report-list">
        {view.reports.map((r) => (
          <li
            key={r.report_id}
            className="rounded-md border border-rally-line p-2 text-sm"
          >
            <p className="whitespace-pre-wrap text-rally-ink">{r.text}</p>
            <p className="mt-1 text-xs text-rally-muted">
              {reportOutcomeLabel(r.outcome)}
              {r.ai_used ? " · read by AI" : ""}
              {r.resolved_at ? " · handled" : ""}
            </p>
            {r.questions.length > 0 && (
              <ul className="mt-1 list-disc pl-5 text-xs text-rally-ink">
                {r.questions.map((q) => (
                  <li key={q}>{q}</li>
                ))}
              </ul>
            )}
            {r.pass_claims.length > 0 && (
              <p
                className="mt-1 text-xs text-rally-ink"
                data-testid="recap-pass-claims"
              >
                The report says{" "}
                {r.pass_claims
                  .map(
                    (c) =>
                      `${studentName.get(c.student_id) ?? "a child"} passed ${
                        names.get(c.skill_id) ?? "a skill"
                      }`,
                  )
                  .join(", ")}
                . That is not recorded as a pass until the lead coach or owner adds it
                to this recap and saves, or checks it on the class&apos;s{" "}
                {skillsHref ? (
                  <Link
                    href={skillsHref as Parameters<typeof Link>[0]["href"]}
                    className="underline"
                    data-testid="recap-skills-link"
                  >
                    skills page
                  </Link>
                ) : (
                  "skills page"
                )}
                .
              </p>
            )}
            {r.pass_claims
              .filter((c) => canAddPass(c.student_id, c.skill_id))
              .map((c) => (
                <Button
                  key={`${c.student_id}:${c.skill_id}`}
                  variant="secondary"
                  size="sm"
                  className="mr-2 mt-2"
                  data-testid={`recap-claim-add-${c.student_id}-${c.skill_id}`}
                  onClick={() => onAddPass(c.student_id, c.skill_id)}
                >
                  {`Add pass: ${studentName.get(c.student_id) ?? "child"}, ${
                    names.get(c.skill_id) ?? "skill"
                  }`}
                </Button>
              ))}
            {view.can_resolve &&
              r.outcome === "sent_to_owner" &&
              !r.resolved_at && (
                <Button
                  variant="secondary"
                  size="sm"
                  className="mt-2"
                  disabled={resolve.isPending}
                  onClick={() => resolve.mutate(r.report_id)}
                >
                  Mark handled
                </Button>
              )}
          </li>
        ))}
      </ul>
    </section>
  );
}
