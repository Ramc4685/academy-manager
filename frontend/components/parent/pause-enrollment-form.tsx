"use client";

import { useState } from "react";
import { useMutation, useQueryClient } from "@tanstack/react-query";

import { Button } from "@/components/ds/button";
import { createParentPauseRequest } from "@/lib/api/parent";

/**
 * Ask the academy to pause one enrollment.
 *
 * Issue #843 moved this off the Payments page: pausing a class is a decision
 * about the class, not about money, and sitting it next to "Set up autopay"
 * made a parent choose between two unrelated things on the billing screen.
 * The form itself is unchanged — same fields, same contract
 * (POST /parent/pause-requests), same validation.
 */
export function PauseEnrollmentForm({
  enrollmentId,
  onDone,
  onCancel,
}: {
  enrollmentId: string;
  onDone?: () => void;
  onCancel: () => void;
}) {
  const queryClient = useQueryClient();
  const [pauseKind, setPauseKind] = useState<"fixed" | "indefinite">("fixed");
  // Blank by default: resuming "today" is never a valid pause, so force an
  // explicit future choice (the submit button stays disabled until set).
  const [resumeOn, setResumeOn] = useState("");
  const [reviewOn, setReviewOn] = useState(dateFromOffset(14));
  const [reason, setReason] = useState("");

  const pauseMutation = useMutation({
    mutationFn: () =>
      createParentPauseRequest({
        enrollment_id: enrollmentId,
        period: pauseKind === "fixed" ? resumeOn.slice(0, 7) : undefined,
        pause_kind: pauseKind,
        resume_on: pauseKind === "fixed" ? resumeOn : null,
        review_on: pauseKind === "indefinite" ? reviewOn : null,
        reason: reason || undefined,
      }),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: ["parent", "pause-requests"] });
      onDone?.();
      onCancel();
    },
  });

  return (
    <div
      data-testid="pause-enrollment-form"
      className="mt-3 rounded-xl border border-rally-line bg-white p-3"
    >
      <p className="mb-3 text-xs text-rally-muted">
        This pauses your child&apos;s class enrollment (and its billing) — it does not change
        your autopay payment method.
      </p>
      <div className="space-y-3">
        <fieldset className="space-y-2">
          <legend className="text-xs font-medium text-rally-muted">Pause type</legend>
          <div className="grid grid-cols-2 gap-2">
            <label
              className={`flex min-h-touch items-center gap-2 rounded-xl border px-3 text-sm ${
                pauseKind === "fixed" ? "border-rally-cobalt-600" : "border-rally-line"
              }`}
            >
              <input
                type="radio"
                name={`pause-kind-${enrollmentId}`}
                value="fixed"
                checked={pauseKind === "fixed"}
                onChange={() => setPauseKind("fixed")}
              />
              Fixed date
            </label>
            <label
              className={`flex min-h-touch items-center gap-2 rounded-xl border px-3 text-sm ${
                pauseKind === "indefinite" ? "border-rally-cobalt-600" : "border-rally-line"
              }`}
            >
              <input
                type="radio"
                name={`pause-kind-${enrollmentId}`}
                value="indefinite"
                checked={pauseKind === "indefinite"}
                onChange={() => setPauseKind("indefinite")}
              />
              Indefinite
            </label>
          </div>
        </fieldset>
        {pauseKind === "fixed" ? (
          <label className="block text-xs font-medium text-rally-muted">
            Resume date
            <input
              type="date"
              value={resumeOn}
              min={dateFromOffset(1)}
              onChange={(e) => setResumeOn(e.target.value)}
              className="mt-1 h-11 w-full rounded-xl border border-rally-line px-3 text-sm text-rally-ink outline-none transition-colors focus:border-rally-cobalt-600 focus:ring-2 focus:ring-rally-cobalt-600/15"
            />
          </label>
        ) : (
          <label className="block text-xs font-medium text-rally-muted">
            Review date
            <input
              type="date"
              value={reviewOn}
              onChange={(e) => setReviewOn(e.target.value)}
              className="mt-1 h-11 w-full rounded-xl border border-rally-line px-3 text-sm text-rally-ink outline-none transition-colors focus:border-rally-cobalt-600 focus:ring-2 focus:ring-rally-cobalt-600/15"
            />
          </label>
        )}
        <p className="text-xs text-rally-subtle">
          {pauseKind === "fixed"
            ? "We will attempt to resume this enrollment on the requested date if a seat is available."
            : "The academy will review this pause on the selected date so billing cannot remain deferred without follow-up."}
        </p>
        <label className="block text-xs font-medium text-rally-muted">
          Reason
          <textarea
            value={reason}
            onChange={(e) => setReason(e.target.value)}
            rows={3}
            className="mt-1 w-full rounded-xl border border-rally-line px-3 py-2 text-sm text-rally-ink outline-none transition-colors focus:border-rally-cobalt-600 focus:ring-2 focus:ring-rally-cobalt-600/15"
          />
        </label>
        {pauseMutation.isError && (
          <p role="alert" className="text-xs text-status-red-800">
            Could not send the pause request. Please try again.
          </p>
        )}
        <div className="flex gap-2">
          <Button
            type="button"
            variant="primary"
            size="lg"
            onClick={() => pauseMutation.mutate()}
            disabled={
              pauseMutation.isPending ||
              (pauseKind === "fixed" ? !resumeOn || resumeOn <= currentDate() : !reviewOn)
            }
            className="flex-1 rounded-xl disabled:opacity-60"
          >
            {pauseMutation.isPending ? "Sending…" : "Submit"}
          </Button>
          <Button
            type="button"
            variant="secondary"
            size="lg"
            onClick={onCancel}
            className="rounded-xl"
          >
            Cancel
          </Button>
        </div>
      </div>
    </div>
  );
}

function currentDate(): string {
  const now = new Date();
  return `${now.getFullYear()}-${String(now.getMonth() + 1).padStart(2, "0")}-${String(now.getDate()).padStart(2, "0")}`;
}

function dateFromOffset(days: number): string {
  const value = new Date();
  value.setDate(value.getDate() + days);
  return `${value.getFullYear()}-${String(value.getMonth() + 1).padStart(2, "0")}-${String(value.getDate()).padStart(2, "0")}`;
}
