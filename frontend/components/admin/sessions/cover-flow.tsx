"use client";

/**
 * S66 "Coach is sick" (docs/design/coach-sick.md, D-20, D-21): from Today,
 * pick the coach and class dates, then per date assign a free coach, cancel
 * the date or leave it, review every consequence (who is emailed, each
 * family's credit) and confirm. Confirm is the only button that changes
 * anything; each date is applied on its own, so one failure leaves the
 * others done and can be retried in place.
 */

import { useEffect, useMemo, useState } from "react";
import { useQueries, useQuery, useQueryClient } from "@tanstack/react-query";

import {
  assignCover,
  cancelSessionOccurrence,
  getCancelPreview,
  getCoachCoverDates,
  getCoverOptions,
  listAdminUsers,
  type CoverOptions,
  type CreditMissedClassResponse,
} from "@/lib/api/admin";
import { assignableCoaches } from "@/lib/admin/coach-roles";
import { academyDateISO } from "@/lib/format/academy-time";
import { useOnline } from "@/lib/pwa/online";
import { queryKeys } from "@/lib/query/keys";
import { Button } from "@/components/ds/button";
import { Modal } from "@/components/ds/modal";
import { useToast } from "@/components/ds/toast";

import {
  DEFAULT_CANCEL_REASON,
  cancelResultLine,
  classDateLabel,
  coverResultLine,
  coverReviewLines,
  creditRows,
  creditTotal,
  readyToConfirm,
  type DateChoice,
} from "./cover-flow.logic";

type Step = 1 | 2 | 3 | "done";
type Result = { ok: boolean; line: string };

function errorText(err: unknown): string {
  const status = (err as { status?: number } | null)?.status;
  if (status === 409) return "This class date changed while you were working. Review it again.";
  return "We could not check this class date.";
}

export function CoverFlow({
  initialOccurrenceId,
  timezone,
  onClose,
}: {
  /** From "Find cover" (a coach asked): open at step 2 for that date. */
  initialOccurrenceId?: string | null;
  timezone: string | null | undefined;
  onClose: () => void;
}) {
  const online = useOnline();
  const queryClient = useQueryClient();
  const { toast } = useToast();
  const [step, setStep] = useState<Step>(initialOccurrenceId ? 2 : 1);
  const [coachId, setCoachId] = useState("");
  const [ticked, setTicked] = useState<string[]>(initialOccurrenceId ? [initialOccurrenceId] : []);
  const [choices, setChoices] = useState<Record<string, DateChoice>>({});
  const [notify, setNotify] = useState(true);
  const [reasons, setReasons] = useState<Record<string, string>>({});
  const [cancelNotify, setCancelNotify] = useState<Record<string, boolean>>({});
  const [results, setResults] = useState<Record<string, Result>>({});
  const [working, setWorking] = useState(false);

  const coaches = useQuery({
    queryKey: queryKeys.admin.users("coach"),
    queryFn: () => listAdminUsers("coach"),
    enabled: step === 1,
  });
  const dates = useQuery({
    queryKey: queryKeys.admin.coverDates(coachId),
    queryFn: () => getCoachCoverDates(coachId),
    enabled: Boolean(coachId) && step === 1,
  });
  const options = useQuery({
    queryKey: queryKeys.admin.coverOptions(ticked),
    queryFn: () => getCoverOptions(ticked),
    enabled: ticked.length > 0 && step !== 1,
  });
  const optionsById = useMemo(
    () => new Map((options.data?.options ?? []).map((o) => [o.occurrence_id, o])),
    [options.data],
  );
  const cancelIds = Object.entries(choices)
    .filter(([, c]) => c.kind === "cancel")
    .map(([id]) => id);
  const previews = useQueries({
    queries: cancelIds.map((id) => ({
      queryKey: queryKeys.admin.cancelPreview(id),
      queryFn: () => getCancelPreview(id),
      enabled: step === 3,
      retry: false,
    })),
  });
  const previewById: Record<string, CreditMissedClassResponse | undefined> = {};
  cancelIds.forEach((id, i) => (previewById[id] = previews[i]?.data));

  // Today's dates are pre-ticked when a coach's dates load.
  useEffect(() => {
    if (!dates.data) return;
    const today = academyDateISO(timezone);
    setTicked(
      (dates.data.dates ?? [])
        .filter((d) => academyDateISO(timezone, new Date(d.start_at)) === today)
        .map((d) => d.occurrence_id),
    );
  }, [dates.data, timezone]);

  // Every date starts on "Assign cover" when someone is free, else "Leave as it is".
  useEffect(() => {
    if (!options.data) return;
    setChoices((prev) => {
      const next: Record<string, DateChoice> = {};
      for (const o of (options.data.options ?? [])) {
        next[o.occurrence_id] =
          prev[o.occurrence_id] ?? (o.free.length > 0 ? { kind: "cover", coachId: null } : { kind: "leave" });
      }
      return next;
    });
  }, [options.data]);

  const coachName = (coaches.data?.users ?? []).find((u) => u.user_id === coachId)?.display_name ?? "This coach";

  async function applyOne(id: string): Promise<void> {
    const choice = choices[id];
    const opt = optionsById.get(id);
    if (!choice || !opt || choice.kind === "leave") return;
    const title = classDateLabel(opt.start_at, timezone);
    try {
      if (choice.kind === "cover" && choice.coachId) {
        const res = await assignCover(id, { replacement_coach_id: choice.coachId, notify_families: notify });
        const cover = opt.free.find((c) => c.coach_id === choice.coachId)?.name ?? "The cover coach";
        setResults((r) => ({ ...r, [id]: { ok: true, line: coverResultLine(title, cover, res.families_notified, notify) } }));
      } else if (choice.kind === "cancel") {
        const res = await cancelSessionOccurrence(id, {
          reason: (reasons[id] ?? DEFAULT_CANCEL_REASON).trim(),
          notify: cancelNotify[id] ?? true,
        });
        setResults((r) => ({
          ...r,
          [id]: { ok: true, line: cancelResultLine(title, res.credits_issued, res.credit_total_cents ?? 0, res.notified) },
        }));
      }
    } catch (err) {
      const verb = choice.kind === "cover" ? "could not assign cover" : "could not cancel";
      const detail = (err as { status?: number } | null)?.status === 409 ? ` ${errorText(err)}` : " Try again.";
      setResults((r) => ({ ...r, [id]: { ok: false, line: `${title}: ${verb}.${detail}` } }));
    }
  }

  async function applyAll(ids: string[]): Promise<void> {
    setWorking(true);
    for (const id of ids) await applyOne(id);
    setWorking(false);
    setStep("done");
  }

  function done() {
    const ok = Object.values(results).filter((r) => r.ok).length;
    if (ok > 0) toast({ kind: "success", title: `Cover sorted for ${ok} class ${ok === 1 ? "date" : "dates"}.` });
    void queryClient.invalidateQueries({ queryKey: queryKeys.admin.today() });
    void queryClient.invalidateQueries({ queryKey: ["admin", "dashboard"] });
    onClose();
  }

  const stepLabel = step === "done" ? "Done" : `${step} of 3`;
  const actionable = Object.entries(choices).filter(([, c]) => c.kind !== "leave").map(([id]) => id);

  return (
    <Modal
      open
      onClose={onClose}
      size="lg"
      title={
        <span className="flex items-baseline justify-between gap-2" aria-live="polite">
          <span>Coach is sick</span>
          <span className="text-sm font-normal text-rally-muted">{stepLabel}</span>
        </span>
      }
    >
      <div className="max-h-[70vh] space-y-4 overflow-y-auto" data-testid="cover-flow">
        {!online ? <p role="alert" className="text-sm text-red-700">This needs a connection.</p> : null}

        {step === 1 ? (
          <>
            <p className="text-sm text-rally-muted">Which coach, and which class dates?</p>
            <label className="block text-sm font-semibold">
              Coach
              <select
                className="mt-1 block w-full rounded-md border border-rally-line px-3 py-2"
                value={coachId}
                onChange={(e) => setCoachId(e.target.value)}
                data-testid="cover-flow-coach"
              >
                <option value="">Choose a coach</option>
                {assignableCoaches(coaches.data?.users ?? []).map((u) => (
                  <option key={u.user_id} value={u.user_id}>
                    {u.display_name}
                  </option>
                ))}
              </select>
            </label>
            {coachId && dates.isLoading ? <p className="text-sm text-rally-muted">Loading class dates…</p> : null}
            {coachId && dates.isError ? <p role="alert" className="text-sm text-red-700">{errorText(dates.error)}</p> : null}
            {dates.data && (dates.data.dates ?? []).length === 0 ? (
              <p className="text-sm text-rally-muted">{coachName} has no class dates in the next two weeks.</p>
            ) : null}
            {coachId && dates.data && (dates.data.dates ?? []).length > 0 ? (
              <fieldset className="space-y-1">
                <legend className="text-sm font-semibold">{coachName}&apos;s class dates</legend>
                {(dates.data.dates ?? []).map((d) => (
                  <label key={d.occurrence_id} className="flex min-h-11 items-start gap-2 text-sm">
                    <input
                      type="checkbox"
                      className="mt-1"
                      checked={ticked.includes(d.occurrence_id)}
                      onChange={(e) =>
                        setTicked((t) =>
                          e.target.checked ? [...t, d.occurrence_id] : t.filter((x) => x !== d.occurrence_id),
                        )
                      }
                    />
                    <span>
                      {classDateLabel(d.start_at, timezone)}
                      <span className="block text-rally-muted">
                        {d.title} · {d.enrolled_count} enrolled
                      </span>
                    </span>
                  </label>
                ))}
              </fieldset>
            ) : null}
            <div className="flex justify-end gap-2">
              <Button variant="secondary" onClick={onClose}>Cancel</Button>
              <Button disabled={ticked.length === 0 || !online} onClick={() => setStep(2)} data-testid="cover-flow-continue">
                Continue
              </Button>
            </div>
          </>
        ) : null}

        {step === 2 ? (
          <>
            {options.isLoading ? <p className="text-sm text-rally-muted">Checking who is free…</p> : null}
            {options.isError ? (
              <p role="alert" className="text-sm text-red-700">
                {errorText(options.error)}{" "}
                <button type="button" className="underline" onClick={() => void options.refetch()}>Retry</button>
              </p>
            ) : null}
            {(options.data?.options ?? []).map((o) => (
              <DateBlock
                key={o.occurrence_id}
                opt={o}
                timezone={timezone}
                choice={choices[o.occurrence_id] ?? { kind: "leave" }}
                onChoice={(c) => setChoices((prev) => ({ ...prev, [o.occurrence_id]: c }))}
              />
            ))}
            {Object.values(choices).some((c) => c.kind === "cover") ? (
              <label className="flex min-h-11 items-start gap-2 border-t border-rally-line pt-3 text-sm">
                <input type="checkbox" className="mt-1" checked={notify} onChange={(e) => setNotify(e.target.checked)} data-testid="cover-flow-notify" />
                <span>Tell the families about the cover coach (by email and in the app)</span>
              </label>
            ) : null}
            <div className="flex justify-between gap-2">
              <Button variant="secondary" onClick={() => setStep(1)} disabled={Boolean(initialOccurrenceId)}>Back</Button>
              <Button
                disabled={actionable.length === 0 || Object.values(choices).some((c) => c.kind === "cover" && !c.coachId)}
                onClick={() => setStep(3)}
                data-testid="cover-flow-review"
              >
                Review
              </Button>
            </div>
          </>
        ) : null}

        {step === 3 ? (
          <>
            <p className="text-sm font-semibold">Check before you confirm</p>
            {actionable.map((id) => {
              const opt = optionsById.get(id);
              const choice = choices[id];
              if (!opt || !choice) return null;
              const preview = previewById[id];
              const previewQuery = previews[cancelIds.indexOf(id)];
              return (
                <section key={id} className="rounded-lg border border-rally-line p-3 text-sm" data-testid={`cover-review-${id}`}>
                  <p className="font-semibold">
                    {classDateLabel(opt.start_at, timezone)} · {opt.title}
                  </p>
                  {choice.kind === "cover" && choice.coachId ? (
                    coverReviewLines(opt, choice.coachId, notify).map((line) => <p key={line}>{line}</p>)
                  ) : null}
                  {choice.kind === "cancel" ? (
                    <>
                      <p>This class date is cancelled.</p>
                      {previewQuery?.isLoading ? <p className="text-rally-muted">Working out credits…</p> : null}
                      {previewQuery?.isError ? <p role="alert" className="text-red-700">{errorText(previewQuery.error)}</p> : null}
                      {preview?.schedule_changed ? (
                        <p role="alert" className="text-red-700">
                          Billing has not laid out this date, so it cannot be cancelled here. Cancel it from the class page.
                        </p>
                      ) : null}
                      {preview && !preview.schedule_changed ? (
                        <table className="mt-2 w-full">
                          <thead>
                            <tr className="text-left text-rally-muted">
                              <th scope="col">Family</th>
                              <th scope="col" className="text-right">Credit</th>
                            </tr>
                          </thead>
                          <tbody>
                            {creditRows(preview).map((row, i) => (
                              <tr key={`${row.who}-${i}`}>
                                <td>{row.who}</td>
                                <td className="text-right tabular-nums">{row.credit}</td>
                              </tr>
                            ))}
                            <tr className="font-semibold">
                              <td>Total credited</td>
                              <td className="text-right tabular-nums" data-testid={`cover-credit-total-${id}`}>{creditTotal(preview)}</td>
                            </tr>
                          </tbody>
                        </table>
                      ) : null}
                      <p className="mt-1">The coach is not paid for it.</p>
                      <label className="mt-2 block font-semibold">
                        Reason (families see this)
                        <input
                          className="mt-1 block w-full rounded-md border border-rally-line px-3 py-2 font-normal"
                          value={reasons[id] ?? DEFAULT_CANCEL_REASON}
                          maxLength={500}
                          required
                          onChange={(e) => setReasons((r) => ({ ...r, [id]: e.target.value }))}
                        />
                      </label>
                      <label className="mt-2 flex min-h-11 items-start gap-2">
                        <input
                          type="checkbox"
                          className="mt-1"
                          checked={cancelNotify[id] ?? true}
                          onChange={(e) => setCancelNotify((n) => ({ ...n, [id]: e.target.checked }))}
                        />
                        <span>Email the families and the coach</span>
                      </label>
                    </>
                  ) : null}
                </section>
              );
            })}
            <div className="flex justify-between gap-2">
              <Button variant="secondary" onClick={() => setStep(2)}>Back</Button>
              <Button
                disabled={
                  working ||
                  !online ||
                  !readyToConfirm(
                    Object.fromEntries(actionable.map((id) => [id, choices[id] as DateChoice])),
                    previewById,
                    Object.fromEntries(actionable.map((id) => [id, reasons[id] ?? DEFAULT_CANCEL_REASON])),
                  )
                }
                onClick={() => void applyAll(actionable)}
                data-testid="cover-flow-confirm"
              >
                {working ? "Working…" : "Confirm"}
              </Button>
            </div>
          </>
        ) : null}

        {step === "done" ? (
          <>
            <ul className="space-y-2 text-sm" data-testid="cover-flow-results">
              {actionable.map((id) => {
                const r = results[id];
                if (!r) return null;
                return (
                  <li key={id} role={r.ok ? undefined : "alert"} className="flex items-start justify-between gap-2">
                    <span>
                      <span aria-hidden="true">{r.ok ? "✓ " : "✕ "}</span>
                      {r.line}
                    </span>
                    {!r.ok ? (
                      <Button size="sm" variant="secondary" disabled={working} onClick={() => void applyAll([id])}>
                        Retry
                      </Button>
                    ) : null}
                  </li>
                );
              })}
            </ul>
            <div className="flex justify-end">
              <Button onClick={done} data-testid="cover-flow-done">Done</Button>
            </div>
          </>
        ) : null}
      </div>
    </Modal>
  );
}

export function DateBlock({
  opt,
  timezone,
  choice,
  onChoice,
}: {
  opt: CoverOptions;
  timezone: string | null | undefined;
  choice: DateChoice;
  onChoice: (c: DateChoice) => void;
}) {
  const name = `cover-choice-${opt.occurrence_id}`;
  const nobodyFree = opt.free.length === 0;
  return (
    <fieldset className="rounded-lg border border-rally-line p-3 text-sm" data-testid={`cover-date-${opt.occurrence_id}`}>
      <legend className="px-1 font-semibold">
        {classDateLabel(opt.start_at, timezone)} · {opt.title} · {opt.enrolled_count} enrolled
      </legend>
      <label className="flex min-h-11 items-center gap-2">
        <input
          type="radio"
          name={name}
          disabled={nobodyFree}
          checked={choice.kind === "cover"}
          onChange={() => onChoice({ kind: "cover", coachId: null })}
        />
        Assign cover
      </label>
      <div className="ml-6 space-y-1">
        <p className="text-xs font-semibold uppercase tracking-wide text-rally-muted">Free at this time</p>
        {nobodyFree ? (
          <p className="text-rally-muted">
            No other coach is free at this time. Cancel the class date, or leave it and call a coach.
          </p>
        ) : (
          <fieldset disabled={choice.kind !== "cover"}>
            {opt.free.map((c) => (
              <label key={c.coach_id} className="flex min-h-11 items-center gap-2">
                <input
                  type="radio"
                  name={`${name}-coach`}
                  checked={choice.kind === "cover" && choice.coachId === c.coach_id}
                  onChange={() => onChoice({ kind: "cover", coachId: c.coach_id })}
                  data-testid={`cover-free-${opt.occurrence_id}-${c.coach_id}`}
                />
                {c.name}
              </label>
            ))}
          </fieldset>
        )}
        {opt.busy.length > 0 ? (
          <>
            <p className="text-xs font-semibold uppercase tracking-wide text-rally-muted">Teaching then</p>
            {opt.busy.map((b) => (
              <p key={b.coach_id} className="text-rally-muted" data-testid={`cover-busy-${opt.occurrence_id}-${b.coach_id}`}>
                {b.name} · {b.class_title}
              </p>
            ))}
          </>
        ) : null}
      </div>
      <label className="flex min-h-11 items-center gap-2">
        <input type="radio" name={name} checked={choice.kind === "cancel"} onChange={() => onChoice({ kind: "cancel" })} />
        Cancel this class date
      </label>
      <label className="flex min-h-11 items-center gap-2">
        <input type="radio" name={name} checked={choice.kind === "leave"} onChange={() => onChoice({ kind: "leave" })} />
        Leave as it is
      </label>
    </fieldset>
  );
}
