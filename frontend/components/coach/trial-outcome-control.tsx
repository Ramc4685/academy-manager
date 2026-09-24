"use client";

/**
 * People CRM L3a: "Came" / "Didn't come" on a trial row of the coach's day.
 *
 * Records the trial's outcome (`POST /coach/trials/{id}/outcome`), which is
 * separate from the attendance mark: attendance says who was on court, this
 * closes the trial in the admin Inbox and the Pipeline. Plain buttons, so it
 * works from the keyboard; "Didn't come" asks for a second press before it
 * saves. The backend only accepts trials on classes this coach coaches.
 */

import { useState } from "react";
import { useMutation, useQueryClient } from "@tanstack/react-query";

import { recordCoachTrialOutcome, type TrialOutcome } from "@/lib/api/coach";

const BUTTON =
  "inline-flex min-h-[44px] items-center justify-center rounded-md border px-3 text-sm font-semibold focus:outline-none focus-visible:ring-2 focus-visible:ring-offset-1 focus-visible:ring-[var(--rally-ink)] disabled:opacity-50";

function errorText(err: unknown): string {
  const status = (err as { status?: number } | null)?.status;
  if (status === 409) return "This trial can't be marked yet (not started, cancelled, or already closed).";
  if (status === 404) return "This trial isn't on one of your classes.";
  return "Could not save. Try again.";
}

export function TrialOutcomeControl({
  requestId,
  studentName,
  outcome,
  onSaved,
}: {
  requestId: string;
  studentName: string;
  outcome: TrialOutcome | null | undefined;
  /** Called after a save so the day's roster can refetch. */
  onSaved?: () => void;
}) {
  const queryClient = useQueryClient();
  const [saved, setSaved] = useState<TrialOutcome | null>(outcome ?? null);
  const [confirmNoShow, setConfirmNoShow] = useState(false);

  const mutation = useMutation({
    mutationFn: (value: TrialOutcome) => recordCoachTrialOutcome(requestId, value),
    onSuccess: (res) => {
      setSaved(res.outcome);
      setConfirmNoShow(false);
      if (onSaved) onSaved();
      else void queryClient.invalidateQueries({ queryKey: ["coach"] });
    },
  });

  const current = mutation.isPending ? null : saved;

  return (
    <div
      role="group"
      aria-label={`Trial outcome for ${studentName}`}
      data-testid={`trial-outcome-${requestId}`}
      className="mt-2 flex flex-wrap items-center gap-2"
    >
      <span className="font-mono text-[10px] font-bold uppercase tracking-chip" style={{ color: "var(--rally-muted)" }}>
        Trial
      </span>
      {confirmNoShow ? (
        <>
          <span className="text-sm" style={{ color: "var(--rally-ink)" }}>
            Mark {studentName} as didn&apos;t come?
          </span>
          <button
            type="button"
            data-testid={`trial-outcome-${requestId}-confirm-no-show`}
            className={BUTTON}
            style={{ borderColor: "#dc2626", background: "#dc2626", color: "#fff" }}
            disabled={mutation.isPending}
            onClick={() => mutation.mutate("no_show")}
          >
            {mutation.isPending ? "Saving…" : "Yes, didn't come"}
          </button>
          <button
            type="button"
            className={BUTTON}
            style={{ borderColor: "var(--rally-line)", color: "var(--rally-muted)" }}
            disabled={mutation.isPending}
            onClick={() => setConfirmNoShow(false)}
          >
            Cancel
          </button>
        </>
      ) : (
        <>
          <button
            type="button"
            data-testid={`trial-outcome-${requestId}-came`}
            aria-pressed={current === "came"}
            className={BUTTON}
            style={
              current === "came"
                ? { borderColor: "#065f46", background: "#065f46", color: "#fff" }
                : { borderColor: "var(--rally-muted)", color: "var(--rally-muted)" }
            }
            disabled={mutation.isPending || current === "came"}
            onClick={() => mutation.mutate("came")}
          >
            Came
          </button>
          <button
            type="button"
            data-testid={`trial-outcome-${requestId}-no-show`}
            aria-pressed={current === "no_show"}
            className={BUTTON}
            style={
              current === "no_show"
                ? { borderColor: "#dc2626", background: "#dc2626", color: "#fff" }
                : { borderColor: "var(--rally-muted)", color: "var(--rally-muted)" }
            }
            disabled={mutation.isPending || current === "no_show"}
            onClick={() => setConfirmNoShow(true)}
          >
            Didn&apos;t come
          </button>
        </>
      )}
      {mutation.isError && (
        <p role="alert" className="w-full text-xs text-red-600" data-testid={`trial-outcome-${requestId}-error`}>
          {errorText(mutation.error)}
        </p>
      )}
    </div>
  );
}
