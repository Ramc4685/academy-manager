"use client";

/**
 * Month dates: the academy picks which days have class each month, then
 * publishes the month so parents see it as final (portal calendar, phone
 * calendar feed, optional email). Unticking a date cancels it through the
 * same path as "cancel this date" on a class (#671): coach not paid, families
 * credited only when they fall below the classes they paid for.
 */

import { useState } from "react";
import { useMutation, useQueries, useQuery, useQueryClient } from "@tanstack/react-query";

import { ConfirmActionDialog } from "@/components/admin/confirm-action-dialog";
import { useAcademyTimezone } from "@/components/admin/use-academy-today";
import { Button } from "@/components/ds/button";
import { Card } from "@/components/ds/card";
import {
  cancelSessionOccurrence,
  getSchedulePublish,
  listAdminSessions,
  listSessionOccurrences,
  setSchedulePublish,
  suggestNoClassDates,
} from "@/lib/api/admin";
import { postSessionAnnouncement } from "@/lib/api/v2/announcements";
import {
  creditOutcome,
  datesToCancel,
  groupMonthDates,
  isEditable,
  monthCompleteFrom,
  plainDatesInMonth,
  scheduleAnnouncement,
  type MonthDateClass,
} from "@/lib/admin/month-dates";
import {
  academyMonthKey,
  formatAcademyDate,
  formatAcademyTimeRange,
  monthLabel,
} from "@/lib/format/academy-time";
import { isMonthPublished } from "@/lib/parent/schedule-events";
import { queryKeys } from "@/lib/query/keys";

const PUBLISH_KEY = ["admin", "schedule", "publish"] as const;
// cancel_session_occurrence.py: the date is off but nobody was credited yet.
const NOT_CREDITED = new Set(["billing_sync_failed", "billing_sync_unwired"]);

export default function AdminMonthDatesPage() {
  const queryClient = useQueryClient();
  const tz = useAcademyTimezone();
  const timeZone = tz ?? "UTC";
  const [month, setMonth] = useState<string | null>(null);
  const activeMonth = month ?? academyMonthKey(tz, 1);
  const [noClass, setNoClass] = useState<Set<string>>(new Set());
  const [confirmOpen, setConfirmOpen] = useState(false);
  const [reason, setReason] = useState("");
  const [emailFamilies, setEmailFamilies] = useState(true);
  const [notice, setNotice] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [pasted, setPasted] = useState("");
  const [suggested, setSuggested] = useState<Map<string, string>>(new Map());
  const [suggestNote, setSuggestNote] = useState<string | null>(null);
  // #1207: what each called-off date credited, shown until the next action.
  const [credits, setCredits] = useState<{ id: string; label: string; outcome: string }[]>([]);

  const sessions = useQuery({
    queryKey: queryKeys.admin.sessions("window-all"),
    queryFn: () => listAdminSessions(undefined, { window: "all" }),
  });
  const publish = useQuery({ queryKey: PUBLISH_KEY, queryFn: getSchedulePublish });

  // window=all lists a recurring class by its first date, not its term, so
  // filter on phase only; groupMonthDates drops dates outside the month.
  const inMonth = (sessions.data?.sessions ?? []).filter(
    (s) => s.status !== "cancelled" && s.phase !== "ended",
  );
  // shortcut: one occurrences request per class in the month; fine for a
  // single academy's dozen classes, add a month-wide endpoint if that grows.
  const occurrenceQueries = useQueries({
    queries: inMonth.map((s) => ({
      queryKey: queryKeys.admin.sessionOccurrences(s.session_id),
      queryFn: () => listSessionOccurrences(s.session_id),
    })),
  });
  // Until the academy timezone loads, dates would group by UTC days.
  const loading = tz === null || sessions.isLoading || occurrenceQueries.some((q) => q.isLoading);
  const occurrenceData = occurrenceQueries.map((q) => q.data);
  // A failed request would show a partial month as if it were whole.
  const loadFailed = sessions.isError || occurrenceQueries.some((q) => q.isError);
  const completeFrom = monthCompleteFrom(activeMonth, new Date(), timeZone);

  // A dated series answers every sibling's query with the whole series: keep
  // each date once, under the first class that returned it.
  const seen = new Set<string>();
  const classes: MonthDateClass[] = [];
  inMonth.forEach((s, i) => {
    for (const occurrence of occurrenceData[i]?.occurrences ?? []) {
      if (seen.has(occurrence.occurrence_id)) continue;
      seen.add(occurrence.occurrence_id);
      classes.push({ occurrence, sessionTitle: s.title });
    }
  });
  const dates = groupMonthDates(classes, activeMonth, timeZone);

  const now = new Date();
  const toCancel = datesToCancel(dates, noClass, now);

  function toggle(ids: string[], off: boolean) {
    setNoClass((prev) => {
      const next = new Set(prev);
      for (const id of ids) {
        if (off) next.add(id);
        else next.delete(id);
      }
      return next;
    });
  }

  // Pre-ticks the dates only; the "Call off" confirm stays the one write.
  const suggest = useMutation({
    mutationFn: async () => {
      const classDays = dates.filter((d) => d.classes.some((c) => isEditable(c.occurrence, now))).map((d) => d.day);
      try {
        const answer = await suggestNoClassDates({ text: pasted.trim(), classDates: classDays });
        return { byDay: new Map(answer.no_class.map((n) => [n.date, n.reason])), notes: answer.notes, ai: true };
      } catch {
        // AI off, over its cap or unreadable: read plain dates instead.
        const days = plainDatesInMonth(pasted, activeMonth);
        return { byDay: new Map(classDays.filter((d) => days.has(d)).map((d) => [d, ""])), notes: "", ai: false };
      }
    },
    onSuccess: ({ byDay, notes, ai }) => {
      setSuggested(byDay);
      const ids = dates
        .filter((d) => byDay.has(d.day))
        .flatMap((d) => d.classes.filter((c) => isEditable(c.occurrence, now)).map((c) => c.occurrence.occurrence_id));
      setNoClass(new Set(ids));
      const reasons = [...byDay.values()].filter(Boolean);
      if (reasons.length && !reason.trim()) setReason(reasons[0]);
      setSuggestNote(
        (byDay.size
          ? `Marked ${byDay.size} day(s) as No class${ai ? " from your text" : " from the dates you typed"}. Check them below, then call them off.`
          : ai
            ? "Nothing in the text rules out a class date this month."
            : "No dates from this month found. Write them like Dec 22 or 12/22.") + (notes ? ` ${notes}` : ""),
      );
    },
  });

  const save = useMutation({
    mutationFn: async () => {
      const failed: string[] = [];
      let creditNotSynced = 0;
      let oneTimeSeatsRemoved = 0;
      const outcomes: { id: string; label: string; outcome: string }[] = [];
      const byId = new Map(dates.flatMap((d) => d.classes).map((c) => [c.occurrence.occurrence_id, c]));
      for (const id of toCancel) {
        try {
          const result = await cancelSessionOccurrence(id, { reason: reason.trim(), notify: false });
          const syncFailed = Boolean(result.billing_result && NOT_CREDITED.has(result.billing_result));
          if (syncFailed) creditNotSynced += 1;
          oneTimeSeatsRemoved += result.roster_entries_removed;
          const c = byId.get(id);
          outcomes.push({
            id,
            label: c ? `${formatAcademyDate(c.occurrence.start_at, timeZone)} · ${c.sessionTitle}` : id,
            outcome: syncFailed
              ? "Billing did not run, so nobody was credited yet."
              : creditOutcome(result.credits_issued, result.credit_total_cents ?? 0, result.credit_skips),
          });
        } catch {
          failed.push(id);
        }
      }
      return { failed, creditNotSynced, oneTimeSeatsRemoved, outcomes };
    },
    onSettled: async (outcome) => {
      setNotice(null);
      setError(null);
      await Promise.all(
        inMonth.map((s) =>
          queryClient.invalidateQueries({ queryKey: queryKeys.admin.sessionOccurrences(s.session_id) }),
        ),
      );
      setConfirmOpen(false);
      setNoClass(new Set());
      setReason("");
      setSuggested(new Map());
      setSuggestNote(null);
      setCredits(outcome?.outcomes ?? []);
      const failed = outcome?.failed ?? [];
      const problems: string[] = [];
      if (failed.length) {
        problems.push(
          `${toCancel.length - failed.length} date(s) saved; ${failed.length} could not be called off. They may have started already.`,
        );
      }
      if (outcome?.creditNotSynced) {
        problems.push(
          `Billing did not update for ${outcome.creditNotSynced} date(s), so families were not credited yet. Check Billing Health.`,
        );
      }
      if (problems.length) setError(problems.join(" "));
      else setNotice(`Saved. ${toCancel.length} date(s) are now marked "No class".`);
      if (outcome?.oneTimeSeatsRemoved) {
        setNotice(
          (prev) =>
            `${prev ?? ""} ${outcome.oneTimeSeatsRemoved} make-up or trial booking(s) on those dates were removed; those families are not in the class email, so contact them directly.`.trim(),
        );
      }
    },
  });

  const publishThrough = (() => {
    const current = publish.data?.published_through ?? null;
    return current && current > activeMonth ? current : activeMonth;
  })();

  const publishMonth = useMutation({
    mutationFn: async () => {
      const result = await setSchedulePublish(publishThrough);
      // The month is published from here on, whatever the emails do.
      queryClient.setQueryData(PUBLISH_KEY, result);
      let emailed = 0;
      const notEmailed: string[] = [];
      const partly: string[] = [];
      if (emailFamilies) {
        for (const s of inMonth) {
          const own = dates
            .flatMap((d) => d.classes)
            .filter((c) => c.occurrence.session_id === s.session_id)
            .map((c) => c.occurrence);
          const body = scheduleAnnouncement(s.title, own, monthLabel(activeMonth), timeZone);
          if (!body) continue;
          try {
            const res = await postSessionAnnouncement("admin", s.session_id, { body, urgent: true });
            // A failed send still answers 200: read the delivery result.
            if (res.email_status === "failed") notEmailed.push(s.title);
            else if (res.failed_count > 0) partly.push(`${s.title} (${res.failed_count} not reached)`);
            else if (res.email_status === "sent") emailed += 1;
          } catch {
            notEmailed.push(s.title);
          }
        }
      }
      return { emailed, notEmailed, partly };
    },
    onMutate: () => {
      setNotice(null);
      setError(null);
    },
    onSuccess: ({ emailed, notEmailed, partly }) => {
      setNotice(
        `${monthLabel(activeMonth)} is published.` +
          (emailed ? ` Families in ${emailed} class(es) were emailed the dates.` : ""),
      );
      const problems: string[] = [];
      if (notEmailed.length) problems.push(`These classes were not emailed: ${notEmailed.join(", ")}.`);
      if (partly.length) problems.push(`Some families were not reached: ${partly.join(", ")}.`);
      if (problems.length) setError(`${problems.join(" ")} Post their dates from the class page.`);
    },
    onError: () => setError("Could not publish. Nothing was emailed. Try again."),
  });

  const published = publish.data
    ? publish.data.published_through !== null && isMonthPublished(activeMonth, publish.data.published_through)
    : false;

  return (
    <section data-testid="admin-month-dates" className="space-y-4">
      <div className="flex flex-wrap items-end justify-between gap-3">
        <label className="text-sm font-medium text-rally-ink">
          Month
          <input
            type="month"
            value={activeMonth}
            onChange={(e) => {
              if (!e.target.value) return;
              setMonth(e.target.value);
              setNoClass(new Set());
              setSuggested(new Map());
              setSuggestNote(null);
              setNotice(null);
              setError(null);
              setCredits([]);
            }}
            className="ml-2 min-h-touch rounded-lg border border-rally-line px-3 text-sm"
            data-testid="month-dates-month"
          />
        </label>
        <p className="text-sm text-rally-muted">
          {published ? `${monthLabel(activeMonth)} is published to parents.` : "Not published yet. Parents see these dates as not confirmed."}
        </p>
      </div>

      {notice && (
        <p role="status" className="rounded-lg bg-status-green-50 px-3 py-2 text-sm text-status-green-800">
          {notice}
        </p>
      )}
      {error && (
        <p role="alert" className="rounded-lg bg-status-red-50 px-3 py-2 text-sm text-status-red-800">
          {error}
        </p>
      )}
      {credits.length > 0 && (
        <Card p={16} data-testid="month-dates-credits">
          <h2 className="text-base font-semibold text-rally-ink">Credits for the dates you called off</h2>
          <p className="mt-1 text-sm text-rally-muted">
            Credits come off each family&apos;s next invoice. A family&apos;s record shows every credit under Billing.
          </p>
          <ul className="mt-2 divide-y divide-rally-line">
            {credits.map((c) => (
              <li key={c.id} className="py-2 text-sm" data-testid="month-dates-credit-row">
                <p className="font-semibold text-rally-ink">{c.label}</p>
                <p className="text-rally-muted">{c.outcome}</p>
              </li>
            ))}
          </ul>
        </Card>
      )}

      <Card p={16}>
        <label htmlFor="month-dates-paste" className="text-base font-semibold text-rally-ink">
          Paste the rental agreement or type the days off
        </label>
        <p className="mt-1 text-sm text-rally-muted">
          For example &ldquo;Gym closed Dec 21 &ndash; Jan 2&rdquo; or &ldquo;No class 12/24, 12/31&rdquo;.
          We mark those days below for you to check; nothing changes until you call them off.
        </p>
        <textarea
          id="month-dates-paste"
          value={pasted}
          onChange={(e) => setPasted(e.target.value)}
          maxLength={8000}
          rows={4}
          className="mt-2 w-full rounded-lg border border-rally-line px-3 py-2 text-sm"
          data-testid="month-dates-paste"
        />
        <div className="mt-2 flex flex-wrap items-center gap-3">
          <Button
            type="button"
            variant="secondary"
            disabled={!pasted.trim() || loading || loadFailed || dates.length === 0 || suggest.isPending}
            onClick={() => suggest.mutate()}
            data-testid="month-dates-suggest"
          >
            {suggest.isPending ? "Reading…" : "Mark the days off"}
          </Button>
          {suggestNote && (
            <p role="status" className="text-sm text-rally-muted" data-testid="month-dates-suggest-note">
              {suggestNote}
            </p>
          )}
        </div>
      </Card>

      <Card p={16}>
        <h2 className="text-base font-semibold text-rally-ink">Which days have class?</h2>
        <p className="mt-1 text-sm text-rally-muted">
          Untick a class, or a whole day, when there is no class. Families get a credit only if
          they end up with fewer classes than they paid for. Called-off dates can&apos;t be
          restored here.
        </p>
        {loadFailed ? (
          <div role="alert" className="mt-4 rounded-lg bg-status-red-50 px-3 py-2 text-sm text-status-red-800" data-testid="month-dates-load-error">
            Some class dates could not be loaded, so this month may be missing dates.{" "}
            <button
              type="button"
              className="font-semibold underline"
              onClick={() => {
                void sessions.refetch();
                occurrenceQueries.forEach((q) => q.isError && void q.refetch());
              }}
            >
              Try again
            </button>
          </div>
        ) : loading ? (
          <p className="mt-4 text-sm text-rally-subtle">Loading dates…</p>
        ) : dates.length === 0 ? (
          <p className="mt-4 text-sm text-rally-subtle">No classes are scheduled in {monthLabel(activeMonth)}.</p>
        ) : (
          <ul className="mt-3 divide-y divide-rally-line" data-testid="month-dates-list">
            {dates.map((d) => {
              const editable = d.classes.filter((c) => isEditable(c.occurrence, now)).map((c) => c.occurrence.occurrence_id);
              const dayOff = editable.length > 0 && editable.every((id) => noClass.has(id));
              return (
                <li key={d.day} className="py-3" data-testid="month-date-row">
                  <div className="flex items-center justify-between gap-3">
                    <p className="text-sm font-semibold text-rally-ink">
                      {formatAcademyDate(d.classes[0].occurrence.start_at, timeZone)}
                      {suggested.get(d.day) && (
                        <span className="ml-2 text-xs font-normal text-rally-muted">{suggested.get(d.day)}</span>
                      )}
                    </p>
                    {editable.length > 0 && (
                      <label className="flex items-center gap-2 text-xs font-medium text-rally-muted">
                        <input type="checkbox" checked={dayOff} onChange={(e) => toggle(editable, e.target.checked)} />
                        No class this day
                      </label>
                    )}
                  </div>
                  <ul className="mt-1 space-y-1">
                    {d.classes.map(({ occurrence: o, sessionTitle }) => {
                      const cancelled = o.status === "cancelled";
                      const canEdit = isEditable(o, now);
                      const off = cancelled || noClass.has(o.occurrence_id);
                      return (
                        <li key={o.occurrence_id} className="flex items-center justify-between gap-3 text-sm">
                          <label className={`flex items-center gap-2 ${canEdit ? "" : "text-rally-subtle"}`}>
                            <input
                              type="checkbox"
                              checked={!off}
                              disabled={!canEdit}
                              onChange={(e) => toggle([o.occurrence_id], !e.target.checked)}
                              aria-label={`${sessionTitle} has class`}
                            />
                            <span>
                              {sessionTitle} · {formatAcademyTimeRange(o.start_at, o.end_at, timeZone).split(" · ")[1]}
                            </span>
                          </label>
                          <span
                            className={`shrink-0 rounded px-2 py-0.5 text-xs font-semibold ${
                              off ? "bg-status-red-50 text-status-red-800" : "bg-status-green-50 text-status-green-800"
                            }`}
                          >
                            {cancelled ? `No class${o.cancellation_reason ? ` · ${o.cancellation_reason}` : ""}` : off ? "No class (unsaved)" : "Class"}
                          </span>
                        </li>
                      );
                    })}
                  </ul>
                </li>
              );
            })}
          </ul>
        )}
        <div className="mt-4 flex flex-wrap items-center gap-3">
          <Button
            type="button"
            variant="primary"
            disabled={toCancel.length === 0 || save.isPending}
            onClick={() => setConfirmOpen(true)}
            data-testid="month-dates-save"
          >
            {toCancel.length ? `Call off ${toCancel.length} date(s)` : "No changes"}
          </Button>
        </div>
      </Card>

      <Card p={16}>
        <h2 className="text-base font-semibold text-rally-ink">Publish {monthLabel(activeMonth)}</h2>
        <p className="mt-1 text-sm text-rally-muted">
          Publishing marks this month, and any earlier unpublished month, as final in the parent
          portal and adds it to parents&apos; phone calendars. Change a date later and their
          calendars update by themselves.
        </p>
        <label className="mt-3 flex items-center gap-2 text-sm text-rally-ink">
          <input type="checkbox" checked={emailFamilies} onChange={(e) => setEmailFamilies(e.target.checked)} />
          Email each class&apos;s families their class and no-class dates
        </label>
        <Button
          type="button"
          variant={published ? "secondary" : "primary"}
          className="mt-3"
          disabled={publishMonth.isPending || toCancel.length > 0 || loading || loadFailed || completeFrom !== null}
          onClick={() => publishMonth.mutate()}
          data-testid="month-dates-publish"
        >
          {published
            ? `Publish again${emailFamilies ? " and email" : ""}`
            : publishThrough === activeMonth
              ? `Publish ${monthLabel(activeMonth)}`
              : `Publish through ${monthLabel(publishThrough)}`}
        </Button>
        {toCancel.length > 0 && (
          <p className="mt-2 text-xs text-rally-subtle">Save your date changes before publishing.</p>
        )}
        {completeFrom && (
          <p className="mt-2 text-xs text-rally-subtle" data-testid="month-dates-not-complete">
            Weekly classes are added to the schedule 60 days ahead, so {monthLabel(activeMonth)} isn&apos;t
            all there yet. You can call off the dates shown now and publish from{" "}
            {formatAcademyDate(`${completeFrom}T18:00:00Z`, timeZone)}.
          </p>
        )}
      </Card>

      {confirmOpen && (
        <ConfirmActionDialog
          open
          onOpenChange={(open) => !open && setConfirmOpen(false)}
          overline="Month dates"
          title={`Call off ${toCancel.length} date(s) in ${monthLabel(activeMonth)}?`}
          consequence="These dates become No class for every enrolled family. The coach is not paid for them, and a family is credited only if they end up with fewer classes than they paid for. No email goes out now; publish the month to tell families."
          confirmLabel="Call off dates"
          pending={save.isPending}
          reason={{
            label: "Reason families see",
            value: reason,
            onChange: setReason,
            required: true,
            placeholder: "Gym not available",
          }}
          onConfirm={() => save.mutate()}
        />
      )}
    </section>
  );
}
