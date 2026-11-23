"use client";

import { useEffect, useRef, useState } from "react";
import Link from "next/link";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { Button } from "@/components/ds/button";
import type { ApiError } from "@/lib/api/client";
import {
  getClassRecap,
  resolveClassReport,
  saveClassRecap,
  submitClassReport,
  type ChildPractice,
  type ClassRecapView,
  type ClassReport,
} from "@/lib/api/class-recap";
import {
  creditEveryone,
  nextReportAttempt,
  practiceEligible,
  reportOutcomeLabel,
  togglePractice,
  withoutSkill,
  type ReportAttempt,
} from "@/lib/coach/class-recap";
import { queryKeys } from "@/lib/query/keys";

interface Draft {
  taught: string[];
  practice: ChildPractice[];
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
export function afterReportError(
  err: unknown,
  last: ReportAttempt | null,
): { attempt: ReportAttempt | null; message: string } {
  const e = err as ApiError;
  if (e?.status === 409 && e.details?.processing === true) {
    return {
      attempt: last,
      message: "Your report is still being read. Wait a moment, then send it again.",
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
    return <p className="text-sm text-rally-subtle">Loading the class recap…</p>;
  }
  if (query.isError || !query.data) {
    return (
      <p role="alert" className="text-sm text-rally-ink">
        Could not load the class recap.{" "}
        <button type="button" className="underline" onClick={() => void query.refetch()}>
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
  const [draft, setDraft] = useState<Draft>({
    taught: view.taught_skills.map((s) => s.skill_id),
    practice: view.practice,
  });
  const [picked, setPicked] = useState("");
  // "" means every taught skill.
  const [creditSkill, setCreditSkill] = useState("");
  const [error, setError] = useState<string | null>(null);

  const names = new Map(
    [...view.skill_options, ...view.taught_skills].map((s) => [s.skill_id, s.name]),
  );
  const eligible = practiceEligible(view.roster);
  const dirty =
    JSON.stringify(draft) !==
    JSON.stringify({ taught: view.taught_skills.map((s) => s.skill_id), practice: view.practice });

  useEffect(() => onDirtyChange?.(dirty), [dirty, onDirtyChange]);

  const save = useMutation({
    mutationFn: () =>
      saveClassRecap(view.occurrence_id, {
        class_starts_at: view.class_starts_at,
        mutation_id: crypto.randomUUID(),
        expected_revision: view.revision,
        taught_skill_ids: draft.taught,
        practice: draft.practice,
      }),
    onSuccess: (next) => {
      setError(null);
      queryClient.setQueryData(key, next);
    },
    onError: (err) => {
      setError(saveError(err));
      void queryClient.invalidateQueries({ queryKey: key });
    },
  });

  const practised = (studentId: string) =>
    draft.practice.find((p) => p.student_id === studentId)?.skill_ids ?? [];

  return (
    <div className="space-y-5" data-testid="class-recap">
      <section aria-labelledby="recap-taught">
        <h3 id="recap-taught" className="text-sm font-semibold text-rally-ink">
          Taught in this class
        </h3>
        {draft.taught.length === 0 ? (
          <p className="mt-1 text-sm text-rally-subtle">No skills recorded yet.</p>
        ) : (
          <ul className="mt-2 flex flex-wrap gap-2" data-testid="recap-taught-list">
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
            <label className="sr-only" htmlFor={`recap-skill-${view.occurrence_id}`}>
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

      <section aria-labelledby="recap-practice">
        <h3 id="recap-practice" className="text-sm font-semibold text-rally-ink">
          Who practised what
        </h3>
        <p className="mt-1 text-xs text-rally-subtle">
          Only children marked present or late can be credited. Teaching a skill does not mark
          anyone as having practised it.
        </p>
        {eligible.length === 0 ? (
          <p className="mt-2 text-sm text-rally-subtle">
            No one is marked present yet. Mark attendance first.
          </p>
        ) : draft.taught.length === 0 ? (
          <p className="mt-2 text-sm text-rally-subtle">Add a taught skill first.</p>
        ) : (
          <>
          {view.can_edit && (
            <div className="mt-2 flex gap-2">
              <label className="sr-only" htmlFor={`recap-credit-${view.occurrence_id}`}>
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
                      d.taught.includes(creditSkill) ? [creditSkill] : d.taught,
                    ),
                  }))
                }
              >
                {`Credit everyone present (${eligible.length})`}
              </Button>
            </div>
          )}
          <ul className="mt-2 divide-y divide-rally-line" data-testid="recap-practice-grid">
            {eligible.map((child) => (
              <li key={child.student_id} className="py-2">
                <p className="text-sm font-medium text-rally-ink">{child.name}</p>
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
                            practice: togglePractice(d.practice, child.student_id, skillId),
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
          disabled={!dirty || save.isPending}
          onClick={() => save.mutate()}
          data-testid="recap-save"
        >
          {save.isPending ? "Saving…" : "Save recap"}
        </Button>
      )}
      {!view.can_edit && (
        <p className="text-xs text-rally-subtle" data-testid="recap-read-only">
          Only the class&apos;s lead coach or the owner can change this recap.
        </p>
      )}

      {view.reports.length > 0 && (
        <ReportList view={view} names={names} skillsHref={skillsHref} />
      )}
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
      const next = nextReportAttempt(attempt.current, text.trim(), view.ai_enabled && useAi, () =>
        crypto.randomUUID(),
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
    },
    onError: (err) => {
      const next = afterReportError(err, attempt.current);
      attempt.current = next.attempt;
      setError(next.message);
    },
  });

  return (
    <section aria-labelledby={`${id}-title`} className="rounded-lg border border-rally-line p-3">
      <h3 id={`${id}-title`} className="text-sm font-semibold text-rally-ink">
        After-class report
      </h3>
      <p className="mt-1 text-xs text-rally-subtle">
        Describe what the class worked on and who practised what. Name the children who took part,
        or say &quot;everyone&quot;. A report only adds to the recap; it never removes anything.
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
        <details className="mt-2 rounded-md bg-rally-paper p-2" data-testid="recap-ai-options">
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
          <p id={`${id}-ai-note`} className="mt-1 text-xs text-rally-muted" data-testid="recap-ai-note">
            If you tick this, the report goes to the academy&apos;s AI provider with children&apos;s
            names swapped for codes and emails and phone numbers removed. Skills and practice it can
            match to your words are added straight to the recap; anything unclear comes back to you
            as a question. Passes are never recorded from a report. Leave it unticked and the report
            goes to the owner, who enters it by hand.
          </p>
        </details>
      ) : (
        <p className="mt-2 text-xs text-rally-muted" data-testid="recap-ai-off-note">
          This report goes to the owner, who adds it to the recap by hand.
        </p>
      )}
      {error && (
        <p role="alert" className="mt-2 text-sm text-rally-ink">
          {error}
        </p>
      )}
      {recapDirty && (
        <p className="mt-2 text-sm text-rally-ink" data-testid="recap-report-blocked">
          Save or undo your recap changes first. A report updates the recap and would replace
          unsaved edits.
        </p>
      )}
      {result && (
        <p role="status" className="mt-2 text-sm text-rally-ink" data-testid="recap-report-result">
          {reportOutcomeLabel(result.outcome)}
          {result.questions.length > 0 ? `: ${result.questions.join(" ")}` : "."}
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
}: {
  view: ClassRecapView;
  names: Map<string, string>;
  skillsHref?: string;
}) {
  const queryClient = useQueryClient();
  const studentName = new Map(view.roster.map((r) => [r.student_id, r.name]));
  const resolve = useMutation({
    mutationFn: (reportId: string) => resolveClassReport(view.occurrence_id, reportId),
    onSuccess: () => {
      void queryClient.invalidateQueries({
        queryKey: queryKeys.classRecap.occurrence(view.occurrence_id),
      });
      void queryClient.invalidateQueries({ queryKey: queryKeys.classRecap.handoffs() });
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
          <li key={r.report_id} className="rounded-md border border-rally-line p-2 text-sm">
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
              <p className="mt-1 text-xs text-rally-ink" data-testid="recap-pass-claims">
                The report says{" "}
                {r.pass_claims
                  .map(
                    (c) =>
                      `${studentName.get(c.student_id) ?? "a child"} passed ${
                        names.get(c.skill_id) ?? "a skill"
                      }`,
                  )
                  .join(", ")}
                . That is not recorded as a pass: check it on the class&apos;s{" "}
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
            {view.can_resolve && r.outcome === "sent_to_owner" && !r.resolved_at && (
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
