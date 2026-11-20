"use client";

import { useState } from "react";
import { useRouter } from "next/navigation";
import { useMutation } from "@tanstack/react-query";

import { copySession, type AdminSessionView, type CopySessionResponse } from "@/lib/api/admin";
import { DAYS_OF_WEEK } from "@/components/admin/sessions/class-form";
import { Button } from "@/components/ds/button";
import { DialogActions, DialogError, Field, RallyModal as RallyDialog } from "@/components/ds/dialog-chrome";

import { inputClass } from "./format";

/** A0-8: what to tell the admin after the copy, beyond "it worked". */
export function copyClassNotes(result: CopySessionResponse, sourcePriced: boolean): string[] {
  const notes = result.roster
    .filter((row) => !row.ok)
    .map((row) => `${row.full_name} was not added: ${row.message ?? "refused"}`);
  if (sourcePriced && !result.price_copied) {
    notes.unshift("The new class has no fee yet. Ask the owner to set it.");
  }
  return notes;
}

type CopySchedule = { days: string[]; startTime: string; endTime: string };

const sameDays = (a: readonly string[], b: readonly string[]) =>
  a.length === b.length && [...a].sort().join() === [...b].sort().join();

/**
 * Only the schedule fields the admin changed are sent: the server keeps the
 * source's value for anything left out, so a multi-day class stays multi-day.
 */
export function copySchedulePatch(
  session: Pick<AdminSessionView, "days_of_week" | "start_time" | "end_time">,
  next: CopySchedule,
): { days_of_week?: string[]; start_time?: string; end_time?: string } {
  const patch: { days_of_week?: string[]; start_time?: string; end_time?: string } = {};
  if (!sameDays(next.days, session.days_of_week ?? [])) patch.days_of_week = next.days;
  if (next.startTime !== (session.start_time ?? "")) patch.start_time = next.startTime;
  if (next.endTime !== (session.end_time ?? "")) patch.end_time = next.endTime;
  return patch;
}

/** Copy class (A0-8): a new class from this one, optionally with its active students. */
export function CopyClassDialog({
  session,
  open,
  onOpenChange,
}: {
  session: AdminSessionView;
  open: boolean;
  onOpenChange: (open: boolean) => void;
}) {
  const router = useRouter();
  const recurring = Boolean(session.days_of_week?.length);
  const [title, setTitle] = useState(`${session.title} (copy)`);
  const [days, setDays] = useState<string[]>(session.days_of_week ?? []);
  const [startTime, setStartTime] = useState(session.start_time ?? "");
  const [endTime, setEndTime] = useState(session.end_time ?? "");
  const [copyRosterTicked, setCopyRoster] = useState(false);
  const schedulePatch = recurring ? copySchedulePatch(session, { days, startTime, endTime }) : {};
  // The same students in a class meeting at the same time would be enrolled and billed twice.
  const canCopyRoster = recurring && Object.keys(schedulePatch).length > 0;
  const copyRoster = canCopyRoster && copyRosterTicked;
  const [error, setError] = useState<string | null>(null);
  const [done, setDone] = useState<{ sessionId: string; notes: string[] } | null>(null);

  const mutation = useMutation({
    mutationFn: () =>
      copySession(session.session_id, {
        title: title.trim(),
        copy_roster: copyRoster,
        ...schedulePatch,
      }),
    onSuccess: (result) => {
      setError(null);
      const notes = copyClassNotes(result, session.amount_cents != null);
      if (notes.length === 0) {
        router.push(`/admin/sessions/${encodeURIComponent(result.session.session_id)}`);
        return;
      }
      setDone({ sessionId: result.session.session_id, notes });
    },
    onError: (err: Error) => setError(err.message ?? "Could not copy this class."),
  });

  return (
    <RallyDialog
      open={open}
      onOpenChange={(next) => {
        if (!next) setDone(null);
        onOpenChange(next);
      }}
      title="Copy class"
      description={`Start a new class from ${session.title}: same coach, location, capacity, price and family info.`}
      overline="Class"
    >
      {error && <DialogError message={error} />}
      {done ? (
        <div className="space-y-3" data-testid="copy-class-done">
          <p className="text-sm font-semibold text-rally-ink">The new class was created.</p>
          <ul className="list-disc space-y-1 pl-5 text-sm text-amber-900">
            {done.notes.map((note) => (
              <li key={note}>{note}</li>
            ))}
          </ul>
          <DialogActions>
            <Button
              variant="primary"
              size="sm"
              onClick={() => router.push(`/admin/sessions/${encodeURIComponent(done.sessionId)}`)}
            >
              Open new class
            </Button>
          </DialogActions>
        </div>
      ) : (
        <form
          className="space-y-3"
          onSubmit={(event) => {
            event.preventDefault();
            mutation.mutate();
          }}
        >
          <Field label="Class name" required>
            <input
              required
              value={title}
              onChange={(event) => setTitle(event.target.value)}
              className={inputClass}
            />
          </Field>
          {recurring && (
            <div className="grid gap-3 sm:grid-cols-2">
              <fieldset className="sm:col-span-3">
                <legend className="mb-1 text-xs font-semibold text-rally-ink">Days</legend>
                <div className="flex flex-wrap gap-3">
                  {DAYS_OF_WEEK.map((d) => (
                    <label key={d.value} className="flex items-center gap-1.5 text-sm text-rally-ink">
                      <input
                        type="checkbox"
                        className="h-4 w-4 accent-rally-cobalt-600"
                        checked={days.includes(d.value)}
                        onChange={(event) =>
                          setDays((current) =>
                            event.target.checked
                              ? [...current, d.value]
                              : current.filter((v) => v !== d.value),
                          )
                        }
                      />
                      {d.label.slice(0, 3)}
                    </label>
                  ))}
                </div>
              </fieldset>
              <Field label="Starts" required>
                <input
                  type="time"
                  required
                  value={startTime}
                  onChange={(event) => setStartTime(event.target.value)}
                  className={inputClass}
                />
              </Field>
              <Field label="Ends" required>
                <input
                  type="time"
                  required
                  value={endTime}
                  onChange={(event) => setEndTime(event.target.value)}
                  className={inputClass}
                />
              </Field>
            </div>
          )}
          {recurring && (
            <label className="flex items-start gap-2 text-sm text-rally-ink">
              <input
                type="checkbox"
                className="mt-0.5 h-4 w-4 accent-rally-cobalt-600"
                checked={copyRoster}
                disabled={!canCopyRoster}
                onChange={(event) => setCopyRoster(event.target.checked)}
              />
              <span>
                Also enroll this class&apos;s active students
                <span className="block text-xs text-rally-subtle">
                  {canCopyRoster
                    ? "Each is added as on Add to roster: a seat is checked, the family gets the welcome email, and they are billed the new class's full price. A fee override or discount on their current enrollment is not carried over. They stay in this class too."
                    : "Change the days or times first: students can't be in two classes that meet at the same time."}
                </span>
              </span>
            </label>
          )}
          <DialogActions>
            <Button variant="secondary" size="sm" type="button" onClick={() => onOpenChange(false)}>
              Cancel
            </Button>
            <Button
              variant="primary"
              size="sm"
              type="submit"
              disabled={mutation.isPending || !title.trim() || (recurring && days.length === 0)}
            >
              {mutation.isPending ? "Copying…" : "Copy class"}
            </Button>
          </DialogActions>
        </form>
      )}
    </RallyDialog>
  );
}
