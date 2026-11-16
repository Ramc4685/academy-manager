"use client";

import { useEffect, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import {
  getProgressSettings,
  updateProgressSettings,
  type MilestoneKind,
  type ProgressSettings,
  type ShareNameRule,
} from "@/lib/api/curriculum";
import { queryKeys } from "@/lib/query/keys";
import { Button } from "@/components/ds/button";
import { Card } from "@/components/ds/card";
import { Overline } from "@/components/ds/typography";
import { useReportSettingsDirty } from "@/components/admin/settings/settings-dirty-context";

type Row = { kind: MilestoneKind; count: number };
type Form = {
  milestones_enabled: boolean;
  milestones: Row[];
  share_name: ShareNameRule;
};

/** Form starting value for a new row only; the academy picks the real number. */
const NEW_ROW: Row = { kind: "skills_passed", count: 10 };
const MAX_ROWS = 20;

const KIND_LABEL: Record<MilestoneKind, string> = {
  skills_passed: "skills mastered",
  levels_completed: "levels completed",
};

function toForm(data: ProgressSettings): Form {
  return {
    milestones_enabled: Boolean(data.milestones_enabled),
    milestones: (data.milestones ?? []).map(({ kind, count }) => ({
      kind,
      count,
    })),
    share_name: data.share_name ?? "first_name",
  };
}

/** Each threshold may appear once (the server refuses duplicates too). */
export function milestoneFormError(form: Form): string | null {
  const seen = new Set<string>();
  for (const row of form.milestones) {
    if (!Number.isInteger(row.count) || row.count < 1 || row.count > 1000)
      return "Each milestone needs a whole number from 1 to 1000.";
    const key = `${row.kind}:${row.count}`;
    if (seen.has(key)) return "Each milestone may appear once.";
    seen.add(key);
  }
  return null;
}

/**
 * Settings -> Curriculum -> Milestones (L5B). Owner or admin. Off and empty
 * until the academy sets it up; a milestone counts only what a student reaches
 * after it was added, so changes apply going forward. The share-name rule is
 * what a parent's public certificate link shows instead of the full name.
 */
export function MilestonesCard() {
  const queryClient = useQueryClient();
  const query = useQuery({
    queryKey: queryKeys.admin.progressSettings(),
    queryFn: getProgressSettings,
  });
  const [form, setForm] = useState<Form | null>(null);
  const [saved, setSaved] = useState(false);
  useEffect(() => {
    if (query.data) setForm(toForm(query.data));
  }, [query.data]);

  const dirty =
    Boolean(query.data && form) &&
    JSON.stringify(form) !== JSON.stringify(toForm(query.data!));
  useReportSettingsDirty("progress-settings", dirty);
  const error = form ? milestoneFormError(form) : null;

  const mutation = useMutation({
    mutationFn: () => updateProgressSettings(form as Form),
    onSuccess: (data) => {
      queryClient.setQueryData(queryKeys.admin.progressSettings(), data);
      setSaved(true);
    },
  });

  const update = (next: (prev: Form) => Form) => {
    setSaved(false);
    setForm((prev) => (prev ? next(prev) : prev));
  };
  const setRow = (index: number, patch: Partial<Row>) =>
    update((prev) => ({
      ...prev,
      milestones: prev.milestones.map((row, i) =>
        i === index ? { ...row, ...patch } : row,
      ),
    }));

  return (
    <Card p={24} className="max-w-3xl" data-testid="milestones-card">
      <Overline>Milestones and sharing</Overline>
      <p className="mt-2 text-sm text-rally-muted">
        Celebrate a student reaching a number of mastered skills or completed
        levels. Reached milestones show on the parent&apos;s progress page and
        in the evening wins email. A new milestone only counts what students
        reach after you add it.
      </p>
      {query.isError && (
        <p className="mt-3 text-sm text-red-700" role="alert">
          Could not load the milestone settings.
        </p>
      )}
      {form && (
        <>
          <label className="mt-4 flex items-center gap-2 text-sm">
            <input
              type="checkbox"
              checked={form.milestones_enabled}
              onChange={(e) =>
                update((p) => ({ ...p, milestones_enabled: e.target.checked }))
              }
              data-testid="milestones-enabled"
            />
            Celebrate milestones
          </label>
          <ul className="mt-3 space-y-2" data-testid="milestones-rows">
            {form.milestones.map((row, index) => (
              <li
                key={index}
                className="flex flex-wrap items-center gap-2 text-sm"
              >
                <input
                  type="number"
                  min={1}
                  max={1000}
                  value={Number.isNaN(row.count) ? "" : row.count}
                  onChange={(e) =>
                    setRow(index, { count: e.target.valueAsNumber })
                  }
                  aria-label={`Milestone ${index + 1} number`}
                  className="w-24 rounded-md border border-neutral-200 px-2 py-1.5 text-sm dark:border-neutral-700 dark:bg-neutral-900"
                  data-testid={`milestone-count-${index}`}
                />
                <select
                  value={row.kind}
                  onChange={(e) =>
                    setRow(index, { kind: e.target.value as MilestoneKind })
                  }
                  aria-label={`Milestone ${index + 1} type`}
                  className="rounded-md border border-neutral-200 px-2 py-1.5 text-sm dark:border-neutral-700 dark:bg-neutral-900"
                  data-testid={`milestone-kind-${index}`}
                >
                  {(Object.keys(KIND_LABEL) as MilestoneKind[]).map((kind) => (
                    <option key={kind} value={kind}>
                      {KIND_LABEL[kind]}
                    </option>
                  ))}
                </select>
                <Button
                  variant="secondary"
                  size="sm"
                  onClick={() =>
                    update((p) => ({
                      ...p,
                      milestones: p.milestones.filter((_, i) => i !== index),
                    }))
                  }
                  aria-label={`Remove milestone ${index + 1}`}
                >
                  Remove
                </Button>
              </li>
            ))}
          </ul>
          {form.milestones.length < MAX_ROWS && (
            <Button
              className="mt-2"
              variant="secondary"
              size="sm"
              onClick={() =>
                update((p) => ({
                  ...p,
                  milestones: [...p.milestones, NEW_ROW],
                }))
              }
              data-testid="milestones-add"
            >
              Add milestone
            </Button>
          )}
          <fieldset className="mt-5">
            <legend className="text-sm font-medium text-rally-ink">
              On a certificate link a parent shares, show the student as
            </legend>
            <div className="mt-2 grid gap-2">
              {(
                [
                  ["first_name", "First name only"],
                  ["initial", "First initial only"],
                ] as const
              ).map(([value, label]) => (
                <label key={value} className="flex items-center gap-2 text-sm">
                  <input
                    type="radio"
                    name="share_name"
                    checked={form.share_name === value}
                    onChange={() =>
                      update((p) => ({ ...p, share_name: value }))
                    }
                    data-testid={`share-name-${value}`}
                  />
                  {label}
                </label>
              ))}
            </div>
          </fieldset>
          <div className="mt-4 flex flex-wrap items-center gap-3">
            <Button
              variant={dirty ? "volt" : "secondary"}
              size="sm"
              disabled={!dirty || Boolean(error) || mutation.isPending}
              onClick={() => mutation.mutate()}
              data-testid="milestones-save"
            >
              {mutation.isPending ? "Saving…" : "Save milestones"}
            </Button>
            {error && (
              <span className="text-sm text-red-700" role="alert">
                {error}
              </span>
            )}
            {saved && !mutation.isPending && !dirty && (
              <span className="text-sm text-rally-muted">Saved.</span>
            )}
            {mutation.isError && (
              <span className="text-sm text-red-700" role="alert">
                {mutation.error instanceof Error
                  ? mutation.error.message
                  : "Could not save the milestone settings."}
              </span>
            )}
          </div>
        </>
      )}
    </Card>
  );
}
