"use client";

import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import {
  getAdminNurtureSequence,
  previewAdminNurtureStep,
  updateAdminNurtureSequence,
  type NurturePreview,
  type NurtureSequenceView,
  type NurtureStepInput,
} from "@/lib/api/admin";
import { queryKeys } from "@/lib/query/keys";
import { Button } from "@/components/ds/button";
import { Card } from "@/components/ds/card";
import { FormField } from "@/components/ds/form-field";
import { Overline } from "@/components/ds/typography";
import { useReportSettingsDirty } from "@/components/admin/settings/settings-dirty-context";
import { SavedNote, savedAtNow } from "@/components/admin/settings/saved-note";

const INPUT =
  "w-full rounded-md border border-rally-line bg-white px-3 py-2 text-sm text-rally-ink focus:outline-none focus:ring-2 focus:ring-blue-600";

/**
 * Lead nurture sequence (AI strategy Phase 3 C1). Off by default. The backend
 * owns who gets each step, the stop rules and the rendering; this card only
 * edits the owner's text and the switch, and asks the backend for a preview.
 */
export function NurtureSequenceCard() {
  // Here, not in the editor: a save remounts the editor with the new version.
  const [savedAt, setSavedAt] = useState<string | null>(null);
  const query = useQuery({
    queryKey: queryKeys.admin.nurtureSequence(),
    queryFn: getAdminNurtureSequence,
  });
  return (
    <Card p={24} className="max-w-3xl" data-testid="admin-settings-nurture">
      <Overline>Lead follow-up emails</Overline>
      <p className="mt-3 text-sm text-rally-muted">
        Up to three emails to new leads who ticked &ldquo;news and offers&rdquo; on your public
        page, 2, 7 and 21 days after they asked. The acknowledgement they get straight away is
        not changed. Emails stop when they reply or you log a contact with them, you move their
        card on the pipeline, they unsubscribe, or they enroll. Only leads who arrive after you
        switch this on get them.
      </p>
      {query.isLoading ? (
        <div className="mt-5 h-24 animate-pulse rounded-md bg-rally-paper" />
      ) : query.isError ? (
        <p role="alert" className="mt-4 text-sm font-medium text-red-700">
          Could not load the follow-up emails.
        </p>
      ) : query.data ? (
        // Keyed on the saved version so a save (or refetch) resets the draft.
        <NurtureEditor
          key={JSON.stringify(query.data)}
          saved={query.data}
          savedAt={savedAt}
          onSaved={() => setSavedAt(savedAtNow())}
        />
      ) : null}
    </Card>
  );
}

function NurtureEditor({
  saved,
  savedAt,
  onSaved,
}: {
  saved: NurtureSequenceView;
  savedAt: string | null;
  onSaved: () => void;
}) {
  const queryClient = useQueryClient();
  const [enabled, setEnabled] = useState(saved.enabled);
  const [steps, setSteps] = useState<NurtureStepInput[]>(() =>
    saved.steps.map(({ day, subject, body }) => ({ day, subject, body }))
  );
  const dirty =
    enabled !== saved.enabled ||
    steps.some((s, i) => s.subject !== saved.steps[i]?.subject || s.body !== saved.steps[i]?.body);
  useReportSettingsDirty("nurture", dirty);

  const mutation = useMutation({
    mutationFn: () => updateAdminNurtureSequence({ enabled, steps }),
    onSuccess: (view) => {
      onSaved();
      queryClient.setQueryData(queryKeys.admin.nurtureSequence(), view);
    },
  });

  function update(day: number, field: "subject" | "body", value: string) {
    setSteps((prev) => prev.map((s) => (s.day === day ? { ...s, [field]: value } : s)));
  }

  return (
    <div className="mt-5 grid gap-5">
      <label className="flex min-h-12 items-center justify-between gap-4 rounded-md border border-rally-line px-4 text-sm font-medium text-rally-ink">
        Send follow-up emails to new leads
        <input
          type="checkbox"
          checked={enabled}
          data-testid="nurture-enabled"
          onChange={(event) => setEnabled(event.target.checked)}
          className="size-4 accent-blue-600"
        />
      </label>
      <p className="text-xs text-rally-muted" data-testid="nurture-merge-fields">
        You can use {saved.merge_fields.map((f) => `{{${f}}}`).join(", ")}. Leave a day blank to
        skip it.
      </p>
      {steps.map((step) => (
        <StepEditor key={step.day} step={step} onChange={update} />
      ))}
      <div className="flex flex-wrap items-center gap-3">
        <Button
          variant={dirty ? "volt" : "secondary"}
          size="sm"
          disabled={!dirty || mutation.isPending}
          onClick={() => mutation.mutate()}
          data-testid="nurture-save"
        >
          {mutation.isPending ? "Saving..." : "Save follow-up emails"}
        </Button>
        <SavedNote at={savedAt} />
        {mutation.isError && (
          <p role="alert" className="text-sm font-medium text-red-700">
            {mutation.error.message}
          </p>
        )}
      </div>
    </div>
  );
}

function StepEditor({
  step,
  onChange,
}: {
  step: NurtureStepInput;
  onChange: (day: number, field: "subject" | "body", value: string) => void;
}) {
  const [preview, setPreview] = useState<NurturePreview | null>(null);
  const previewMutation = useMutation({
    mutationFn: () => previewAdminNurtureStep(step),
    onSuccess: setPreview,
  });
  const id = `nurture-day-${step.day}`;
  const blank = !(step.subject ?? "").trim() && !(step.body ?? "").trim();
  return (
    <fieldset className="grid gap-3 rounded-md border border-rally-line p-4" data-testid={id}>
      <legend className="px-1 text-sm font-semibold text-rally-ink">Day {step.day}</legend>
      <FormField label="Subject" htmlFor={`${id}-subject`}>
        <input
          id={`${id}-subject`}
          className={INPUT}
          maxLength={150}
          value={step.subject ?? ""}
          onChange={(event) => onChange(step.day, "subject", event.target.value)}
        />
      </FormField>
      <FormField label="Message" htmlFor={`${id}-body`}>
        <textarea
          id={`${id}-body`}
          className={`${INPUT} min-h-28`}
          maxLength={4000}
          value={step.body ?? ""}
          onChange={(event) => onChange(step.day, "body", event.target.value)}
        />
      </FormField>
      <div>
        <Button
          variant="secondary"
          size="sm"
          disabled={blank || previewMutation.isPending}
          onClick={() => previewMutation.mutate()}
        >
          {previewMutation.isPending ? "Loading preview..." : "Preview"}
        </Button>
      </div>
      {previewMutation.isError && (
        <p role="alert" className="text-sm font-medium text-red-700">
          {previewMutation.error.message}
        </p>
      )}
      {preview && (
        <div
          className="rounded-md bg-rally-paper p-3 text-sm text-rally-ink"
          data-testid={`${id}-preview`}
          aria-live="polite"
        >
          <p className="font-semibold">{preview.subject}</p>
          <p className="mt-2 whitespace-pre-wrap">{preview.body_text}</p>
          <p className="mt-2 text-xs text-rally-muted">
            Example class shown. The email adds your logo and an unsubscribe link.
          </p>
        </div>
      )}
    </fieldset>
  );
}
