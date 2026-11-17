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

type ClosureDate = NonNullable<CloseAcademyDatesResponse["dates"]>[number];

/** Class time as the academy reads it, not in the viewer's browser zone. */
function when(iso: string, timeZone: string): string {
  return new Date(iso).toLocaleString(undefined, {
    weekday: "short",
    month: "short",
    day: "numeric",
    hour: "numeric",
    minute: "2-digit",
    timeZone,
  });
}

function dateLine(d: ClosureDate, timeZone: string): string {
  return `${d.session_title ?? "Class"}, ${when(d.start_at, timeZone)}`;
}

function plural(n: number, word: string): string {
  return `${n} ${word}${n === 1 ? "" : "s"}`;
}

function families(n: number): string {
  return `${n} famil${n === 1 ? "y" : "ies"}`;
}

function SkippedList({
  dates,
  timeZone,
}: {
  dates: ClosureDate[];
  timeZone: string;
}) {
  if (dates.length === 0) return null;
  return (
    <ul
      className="mt-2 space-y-1 text-sm text-rally-muted"
      data-testid="closure-skipped"
    >
      {dates.map((d) => (
        <li key={d.occurrence_id}>
          Not cancelled: {dateLine(d, timeZone)}
          {d.skip_reason ? ` (${d.skip_reason})` : ""}
        </li>
      ))}
    </ul>
  );
}

/** The dry run: dates that will be cancelled, and the ones the cancel rules refuse. */
export function ClosurePreview({
  preview,
  pending,
  onApply,
}: {
  preview: CloseAcademyDatesResponse;
  pending: boolean;
  onApply: () => void;
}) {
  const dates = preview.dates ?? [];
  const toCancel = dates.filter((d) => d.status === "would_cancel");
  const refused = dates.filter((d) => d.status === "skipped");
  return (
    <div className="mt-4" data-testid="closure-preview-list">
      {toCancel.length === 0 ? (
        <p className="text-sm text-rally-muted">
          No weekly classes can be cancelled in these dates.
        </p>
      ) : (
        <>
          <p className="text-sm font-medium text-rally-ink">
            {plural(toCancel.length, "class date")} will be cancelled:
          </p>
          <ul className="mt-2 space-y-1 text-sm">
            {toCancel.map((d) => (
              <li key={d.occurrence_id}>{dateLine(d, preview.timezone)}</li>
            ))}
          </ul>
        </>
      )}
      <SkippedList dates={refused} timeZone={preview.timezone} />
      {toCancel.length > 0 && (
        <Button
          className="mt-3"
          disabled={pending}
          onClick={onApply}
          data-testid="closure-apply"
        >
          {pending
            ? "Cancelling..."
            : `Cancel ${plural(toCancel.length, "class date")}`}
        </Button>
      )}
    </div>
  );
}

/** What the closure did, including what the admin still has to do by hand. */
export function ClosureResult({
  done,
  notify,
}: {
  done: CloseAcademyDatesResponse;
  notify: boolean;
}) {
  const dates = done.dates ?? [];
  const cancelled = done.cancelled ?? 0;
  const credits = done.credits_issued ?? 0;
  const affected = done.families_affected ?? 0;
  const emailed = done.families_notified ?? 0;
  const warnings = dates.filter(
    (d) => d.status === "cancelled" && d.billing_warning,
  );
  return (
    <div className="mt-4 text-sm" role="status" data-testid="closure-result">
      <p className="font-medium text-rally-ink">
        {plural(cancelled, "class date")} cancelled
        {credits > 0 ? `, ${plural(credits, "credit")} issued` : ""}
        {notify ? `, ${families(emailed)} emailed` : ""}.
      </p>
      {notify && affected > emailed && !done.notice_failed && (
        <p className="mt-1 text-rally-muted" data-testid="closure-not-emailed">
          {families(affected - emailed)} on these classes{" "}
          {affected - emailed === 1 ? "has" : "have"} no email on file. Tell
          them yourself.
        </p>
      )}
      {done.notice_failed && (
        <p
          className="mt-1 text-red-700"
          role="alert"
          data-testid="closure-notice-failed"
        >
          The family emails did not all send. The classes are cancelled; tell
          the families yourself.
        </p>
      )}
      {warnings.length > 0 && (
        <ul
          className="mt-2 space-y-1 text-red-700"
          role="alert"
          data-testid="closure-billing-warnings"
        >
          {warnings.map((d) => (
            <li key={d.occurrence_id}>
              {dateLine(d, done.timezone)}: {d.billing_warning}
            </li>
          ))}
        </ul>
      )}
      <SkippedList
        dates={dates.filter((d) => d.status === "skipped")}
        timeZone={done.timezone}
      />
    </div>
  );
}

/**
 * Settings -> Academy profile -> Closure dates (L12). Cancels every weekly
 * class date in a range in one step: each date follows the single-date cancel
 * rules (families credited, coach not paid), and each family gets ONE email
 * listing every date it loses. Preview first, then confirm.
 */
type ClosureRequest = {
  start_date: string;
  end_date: string;
  reason: string;
  notify: boolean;
};

export function ClosureDatesCard() {
  const [start, setStart] = useState("");
  const [end, setEnd] = useState("");
  const [reason, setReason] = useState("");
  const [notify, setNotify] = useState(true);
  const [preview, setPreview] = useState<CloseAcademyDatesResponse | null>(
    null,
  );
  // The exact range the preview was made for; confirming sends this, never the live form.
  const [previewed, setPreviewed] = useState<ClosureRequest | null>(null);
  const [done, setDone] = useState<CloseAcademyDatesResponse | null>(null);

  const request = (): ClosureRequest => ({
    start_date: start,
    end_date: end || start,
    reason: reason.trim(),
    notify,
  });
  const previewMutation = useMutation({
    mutationFn: (body: ClosureRequest) =>
      closeAcademyDates({ ...body, dry_run: true }),
    onSuccess: (data, body) => {
      // The form changed while this preview was in flight: drop the stale answer.
      if (JSON.stringify(body) !== JSON.stringify(request())) return;
      setDone(null);
      setPreview(data);
      setPreviewed(body);
    },
  });
  const applyMutation = useMutation({
    mutationFn: (body: ClosureRequest) =>
      closeAcademyDates({ ...body, dry_run: false }),
    onSuccess: (data) => {
      setPreview(null);
      setPreviewed(null);
      setDone(data);
    },
  });
  const edit = (setter: (v: string) => void) => (v: string) => {
    setter(v);
    setPreview(null);
    setPreviewed(null);
  };
  const ready = Boolean(start && reason.trim()) && (!end || end >= start);
  const error = previewMutation.error ?? applyMutation.error;

  return (
    <Card p={24} className="max-w-3xl" data-testid="closure-dates-card">
      <Overline>Closure dates</Overline>
      <p className="mt-2 text-sm text-rally-muted">
        Closed for a holiday or a facility closure? Cancel every weekly class in
        the range at once. Each date is credited the same way as cancelling it
        by hand, and each family gets one email listing all of its cancelled
        classes. You can close dates up to 60 days ahead. One-off classes
        (camps, workshops) are not included: cancel those from the class page.
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
          onChange={(e) => {
            setNotify(e.target.checked);
            setPreview(null);
            setPreviewed(null);
          }}
          data-testid="closure-notify"
        />
        Email families and coaches
      </label>
      <Button
        className="mt-4"
        variant="secondary"
        disabled={!ready || previewMutation.isPending}
        onClick={() => previewMutation.mutate(request())}
        data-testid="closure-preview"
      >
        {previewMutation.isPending ? "Checking..." : "Preview class dates"}
      </Button>
      {error && (
        <p className="mt-3 text-sm text-red-700" role="alert">
          {error instanceof Error
            ? error.message
            : "Could not close these dates."}
        </p>
      )}
      {preview && (
        <ClosurePreview
          preview={preview}
          pending={applyMutation.isPending}
          onApply={() => previewed && applyMutation.mutate(previewed)}
        />
      )}
      {done && <ClosureResult done={done} notify={notify} />}
    </Card>
  );
}
