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
} from "@/lib/api/admin";
import { postSessionAnnouncement } from "@/lib/api/v2/announcements";
import {
  datesToCancel,
  groupMonthDates,
  isEditable,
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
  const loading = sessions.isLoading || occurrenceQueries.some((q) => q.isLoading);
  const occurrenceData = occurrenceQueries.map((q) => q.data);

  // A dated series answers every sibling's query with the whole series: keep
  // each date once, under the first class that returned it.
  const seen = new Set<string>();
  const classes: MonthDateClass[] = [];
  const ownerOf = new Map<string, number>();
  inMonth.forEach((s, i) => {
    for (const occurrence of occurrenceData[i]?.occurrences ?? []) {
      if (seen.has(occurrence.occurrence_id)) continue;
      seen.add(occurrence.occurrence_id);
      ownerOf.set(occurrence.occurrence_id, i);
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

  const save = useMutation({
    mutationFn: async () => {
      const failed: string[] = [];
      for (const id of toCancel) {
        try {
          await cancelSessionOccurrence(id, { reason: reason.trim(), notify: false });
        } catch {
          failed.push(id);
        }
      }
      return failed;
    },
    onSettled: async (failed) => {
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
      if (failed && failed.length) {
        setError(
          `${toCancel.length - failed.length} date(s) saved; ${failed.length} could not be called off. They may have started already.`,
        );
      } else {
        setNotice(`Saved. ${toCancel.length} date(s) are now marked "No class".`);
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
      if (emailFamilies) {
        for (const [i, s] of inMonth.entries()) {
          const own = dates
            .flatMap((d) => d.classes)
            .filter((c) => ownerOf.get(c.occurrence.occurrence_id) === i)
            .map((c) => c.occurrence);
          const body = scheduleAnnouncement(s.title, own, monthLabel(activeMonth), timeZone);
          if (!body) continue;
          try {
            await postSessionAnnouncement("admin", s.session_id, { body, urgent: true });
            emailed += 1;
          } catch {
            notEmailed.push(s.title);
          }
        }
      }
      return { emailed, notEmailed };
    },
    onMutate: () => {
      setNotice(null);
      setError(null);
    },
    onSuccess: ({ emailed, notEmailed }) => {
      setNotice(
        `${monthLabel(activeMonth)} is published.` +
          (emailed ? ` Families in ${emailed} class(es) were emailed the dates.` : ""),
      );
      if (notEmailed.length) {
        setError(`These classes were not emailed: ${notEmailed.join(", ")}. Post their dates from the class page.`);
      }
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
              setNotice(null);
              setError(null);
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

      <Card p={16}>
        <h2 className="text-base font-semibold text-rally-ink">Which days have class?</h2>
        <p className="mt-1 text-sm text-rally-muted">
          Untick a class, or a whole day, when there is no class. Families get a credit only if
          they end up with fewer classes than they paid for. Called-off dates can&apos;t be
          restored here.
        </p>
        {loading ? (
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
          disabled={publishMonth.isPending || toCancel.length > 0 || loading}
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
