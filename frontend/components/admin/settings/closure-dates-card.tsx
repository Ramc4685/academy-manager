"use client";

import { useState } from "react";
import { useMutation } from "@tanstack/react-query";

import {
  closeAcademyDates,
  type CloseAcademyDatesResponse,
} from "@/lib/api/admin";
import { Button } from "@/components/ds/button";
import { Card } from "@/components/ds/card";
import { Overline } from "@/components/ds/typography";

const INPUT =
  "rounded-md border border-neutral-200 px-2 py-1.5 text-sm dark:border-neutral-700 dark:bg-neutral-900";

function when(iso: string): string {
  return new Date(iso).toLocaleString(undefined, {
    weekday: "short",
    month: "short",
    day: "numeric",
    hour: "numeric",
    minute: "2-digit",
  });
}

/**
 * Settings -> Academy profile -> Closure dates (L12). Cancels every class
 * date in a range in one step: each date follows the single-date cancel
 * rules (families credited, coach not paid), and each family gets ONE email
 * listing every date it loses. Preview first, then confirm.
 */
export function ClosureDatesCard() {
  const [start, setStart] = useState("");
  const [end, setEnd] = useState("");
  const [reason, setReason] = useState("");
  const [notify, setNotify] = useState(true);
  const [preview, setPreview] = useState<CloseAcademyDatesResponse | null>(null);
  const [done, setDone] = useState<CloseAcademyDatesResponse | null>(null);

  const payload = (dry_run: boolean) => ({
    start_date: start,
    end_date: end || start,
    reason: reason.trim(),
    notify,
    dry_run,
  });
  const previewMutation = useMutation({
    mutationFn: () => closeAcademyDates(payload(true)),
    onSuccess: (data) => {
      setDone(null);
      setPreview(data);
    },
  });
  const applyMutation = useMutation({
    mutationFn: () => closeAcademyDates(payload(false)),
    onSuccess: (data) => {
      setPreview(null);
      setDone(data);
    },
  });
  const edit = (setter: (v: string) => void) => (v: string) => {
    setter(v);
    setPreview(null);
  };
  const ready = Boolean(start && reason.trim()) && (!end || end >= start);
  const error = previewMutation.error ?? applyMutation.error;
  const count = preview?.dates.length ?? 0;

  return (
    <Card p={24} className="max-w-3xl" data-testid="closure-dates-card">
      <Overline>Closure dates</Overline>
      <p className="mt-2 text-sm text-rally-muted">
        Closed for a holiday or a facility closure? Cancel every class in the
        range at once. Each date is credited the same way as cancelling it by
        hand, and each family gets one email listing all of its cancelled
        classes. You can close dates up to 60 days ahead.
      </p>
      <div className="mt-4 flex flex-wrap items-end gap-3 text-sm">
        <label className="grid gap-1">
          First day closed
          <input
            type="date"
            value={start}
            onChange={(e) => edit(setStart)(e.target.value)}
            className={INPUT}
            data-testid="closure-start"
          />
        </label>
        <label className="grid gap-1">
          Last day closed
          <input
            type="date"
            value={end}
            min={start || undefined}
            onChange={(e) => edit(setEnd)(e.target.value)}
            className={INPUT}
            data-testid="closure-end"
          />
        </label>
        <label className="grid min-w-[14rem] flex-1 gap-1">
          Reason (shown to families)
          <input
            type="text"
            maxLength={500}
            value={reason}
            placeholder="Thanksgiving break"
            onChange={(e) => edit(setReason)(e.target.value)}
            className={INPUT}
            data-testid="closure-reason"
          />
        </label>
      </div>
      <label className="mt-3 flex items-center gap-2 text-sm">
        <input
          type="checkbox"
          checked={notify}
          onChange={(e) => setNotify(e.target.checked)}
          data-testid="closure-notify"
        />
        Email families and coaches
      </label>
      <Button
        className="mt-4"
        variant="secondary"
        disabled={!ready || previewMutation.isPending}
        onClick={() => previewMutation.mutate()}
        data-testid="closure-preview"
      >
        {previewMutation.isPending ? "Checking..." : "Preview class dates"}
      </Button>
      {error && (
        <p className="mt-3 text-sm text-red-700" role="alert">
          {error instanceof Error ? error.message : "Could not close these dates."}
        </p>
      )}
      {preview && (
        <div className="mt-4" data-testid="closure-preview-list">
          {count === 0 ? (
            <p className="text-sm text-rally-muted">
              No scheduled classes fall in these dates.
            </p>
          ) : (
            <>
              <p className="text-sm font-medium text-rally-ink">
                {count} class date{count === 1 ? "" : "s"} will be cancelled:
              </p>
              <ul className="mt-2 space-y-1 text-sm">
                {preview.dates.map((d) => (
                  <li key={d.occurrence_id}>
                    {d.session_title ?? "Class"}, {when(d.start_at)}
                  </li>
                ))}
              </ul>
              <Button
                className="mt-3"
                disabled={applyMutation.isPending}
                onClick={() => applyMutation.mutate()}
                data-testid="closure-apply"
              >
                {applyMutation.isPending
                  ? "Cancelling..."
                  : `Cancel ${count} class date${count === 1 ? "" : "s"}`}
              </Button>
            </>
          )}
        </div>
      )}
      {done && (
        <div className="mt-4 text-sm" role="status" data-testid="closure-result">
          <p className="font-medium text-rally-ink">
            {done.cancelled} class date{done.cancelled === 1 ? "" : "s"} cancelled
            {done.credits_issued > 0 ? `, ${done.credits_issued} credits issued` : ""}
            {notify ? `, ${done.families_notified} families emailed` : ""}.
          </p>
          {done.skipped > 0 && (
            <ul className="mt-2 space-y-1 text-rally-muted">
              {done.dates
                .filter((d) => d.status === "skipped")
                .map((d) => (
                  <li key={d.occurrence_id}>
                    Not cancelled: {d.session_title ?? "Class"}, {when(d.start_at)}
                    {d.skip_reason ? ` (${d.skip_reason})` : ""}
                  </li>
                ))}
            </ul>
          )}
        </div>
      )}
    </Card>
  );
}
