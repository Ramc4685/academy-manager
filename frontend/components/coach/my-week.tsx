"use client";

/**
 * S68: "My week" on Today (docs/design/coach-home.md 3.1, 3.2, 3.6).
 *
 * The cards read the coach schedule the shell already fetches; the 7-day
 * window is presentation only, cut on the academy's calendar.
 */

import Link from "next/link";
import { useQuery } from "@tanstack/react-query";

import { ContactLinks, EmptyState, LaneHeader, Skeleton } from "@/components/ds";
import {
  getCoachAcademy,
  getCoachPathway,
  getCoachProfile,
  type CoachScheduleEntry,
} from "@/lib/api/coach";
import { coachPlanHref } from "@/lib/coach/class-facts";
import { coachScheduleEntryHref } from "@/lib/coach/schedule-links";
import { academyDateISO, formatAcademyTimeRange, formatInAcademyZone } from "@/lib/format/academy-time";
import { queryKeys } from "@/lib/query/keys";

const WEEK_DAYS = 7;
type Href = Parameters<typeof Link>[0]["href"];

function dayNumber(iso: string): number {
  const [y, m, d] = iso.split("-").map(Number);
  return Date.UTC(y, m - 1, d) / 86_400_000;
}

/** Class dates from today through the next 7 days, soonest first, on the academy calendar. */
export function classesThisWeek(
  sessions: readonly CoachScheduleEntry[],
  fallbackTz: string | null | undefined,
  now: Date = new Date(),
): { entry: CoachScheduleEntry; inDays: number }[] {
  return sessions
    .filter((s) => new Date(s.end_at).getTime() > now.getTime())
    .map((entry) => {
      const tz = entry.timezone ?? fallbackTz;
      const inDays = dayNumber(academyDateISO(tz, new Date(entry.start_at))) - dayNumber(academyDateISO(tz, now));
      return { entry, inDays };
    })
    .filter(({ inDays }) => inDays >= 0 && inDays <= WEEK_DAYS)
    .sort((a, b) => Date.parse(a.entry.start_at) - Date.parse(b.entry.start_at));
}

function whenLabel(entry: CoachScheduleEntry, inDays: number, tz: string | null | undefined): string {
  const day = formatInAcademyZone(entry.start_at, entry.timezone ?? tz, {
    weekday: "short",
    month: "short",
    day: "numeric",
  });
  const rel = inDays === 0 ? "TODAY" : inDays === 1 ? "TOMORROW" : `IN ${inDays} DAYS`;
  return `${day.toUpperCase()} · ${rel}`;
}

function ClassCard({
  entry,
  inDays,
  tz,
  myUserId,
  withButtons,
  testId,
}: {
  entry: CoachScheduleEntry;
  inDays: number | null;
  tz: string | null | undefined;
  myUserId: string | undefined;
  withButtons: boolean;
  testId?: string;
}) {
  const zone = entry.timezone ?? tz;
  // shortcut: the schedule only says who leads, so "covering" is not shown yet.
  const assisting = !!myUserId && !!entry.coach_id && entry.coach_id !== myUserId;
  const range = formatAcademyTimeRange(entry.start_at, entry.end_at, zone).split(" · ").slice(1).join(" · ");
  const open = coachScheduleEntryHref(entry, tz);
  const children = entry.enrolled_count;
  return (
    <li data-testid={testId} className="rounded-lg border border-rally-line bg-white p-3 dark:bg-neutral-900">
      <p className="text-xs font-semibold uppercase tracking-wide text-neutral-500">
        {inDays === null
          ? formatInAcademyZone(entry.start_at, zone, { weekday: "short", month: "short", day: "numeric" }).toUpperCase()
          : whenLabel(entry, inDays, tz)}
      </p>
      <h3 className="mt-1 text-base font-semibold">
        {withButtons ? (
          entry.title
        ) : (
          <Link href={open as Href} className="hover:underline">
            {entry.title}
          </Link>
        )}
        {assisting ? " (assisting)" : ""}
      </h3>
      <p className="text-sm text-neutral-600 dark:text-neutral-300">
        {range}
        {entry.location ? ` · ${entry.location}` : ""}
      </p>
      {typeof children === "number" && (
        <p className="text-sm text-neutral-600 dark:text-neutral-300">
          {children} {children === 1 ? "child" : "children"}
        </p>
      )}
      {withButtons && (
        <div className="mt-3 grid grid-cols-2 gap-2">
          <Link
            href={coachPlanHref(academyDateISO(zone, new Date(entry.start_at))) as Href}
            className="flex min-h-touch items-center justify-center rounded-lg border border-rally-line text-sm font-semibold"
          >
            Read the plan
          </Link>
          <Link
            href={open as Href}
            data-testid={testId ? `${testId}-open` : undefined}
            className="flex min-h-touch items-center justify-center rounded-lg border border-rally-line text-sm font-semibold"
          >
            Open class
          </Link>
        </div>
      )}
    </li>
  );
}

/** Below today's classes: the rest of the week, quietly, each card opens its class. */
export function LaterThisWeek({ sessions }: { sessions: readonly CoachScheduleEntry[] }) {
  const { data: academy } = useQuery({ queryKey: queryKeys.coach.academy(), queryFn: getCoachAcademy });
  const { data: profile } = useQuery({ queryKey: queryKeys.coach.profile(), queryFn: getCoachProfile });
  const later = classesThisWeek(sessions, academy?.timezone).filter(({ inDays }) => inDays > 0);
  if (later.length === 0) return null;
  return (
    <div className="mt-6" data-testid="later-this-week">
      <LaneHeader title="Later this week" />
      <ul className="space-y-2">
        {later.map(({ entry, inDays }) => (
          <ClassCard
            key={entry.occurrence_id}
            entry={entry}
            inDays={inDays}
            tz={academy?.timezone}
            myUserId={profile?.user_id}
            withButtons={false}
          />
        ))}
      </ul>
    </div>
  );
}

export function WhoToCall() {
  const { data: academy, isPending } = useQuery({ queryKey: queryKeys.coach.academy(), queryFn: getCoachAcademy });
  const phone = academy?.contact_phone?.trim() || null;
  const email = academy?.contact_email?.trim() || null;
  return (
    <div id="who-to-call" className="mt-6 scroll-mt-20" data-testid="who-to-call">
      <LaneHeader title="Who to call" />
      {isPending ? (
        <Skeleton lines={3} />
      ) : (
        <div className="text-sm text-neutral-700 dark:text-neutral-200">
          <p className="font-medium">{academy?.name ?? "Your academy"}</p>
          {phone || email ? (
            <>
              <ContactLinks phone={phone} email={email} name={academy?.name} className="flex-col items-start" />
              <p className="mt-1">
                Running late or unwell? Call first. You can also tap &quot;I can&apos;t make it&quot; on the class.
              </p>
            </>
          ) : (
            <p>Ask the person who invited you for the academy&apos;s number.</p>
          )}
        </div>
      )}
    </div>
  );
}

export function WhatWeTeachTeaser() {
  const { data } = useQuery({ queryKey: queryKeys.coach.pathway(), queryFn: getCoachPathway });
  const levels = data?.programs[0]?.levels ?? [];
  return (
    <div className="mt-6" data-testid="what-we-teach">
      <LaneHeader title="What we teach" />
      {levels.length > 0 && (
        <ul className="text-sm text-neutral-700 dark:text-neutral-200">
          {levels.slice(0, 2).map((level) => (
            <li key={level.level_id}>
              Level {level.sequence} · {level.name}
            </li>
          ))}
        </ul>
      )}
      <Link
        href="/coach/pathway"
        className="mt-1 inline-flex min-h-touch items-center text-sm font-semibold text-rally-cobalt-700 underline-offset-2 hover:underline"
      >
        {levels.length > 0 ? `See all ${levels.length} levels and lessons →` : "See what we teach →"}
      </Link>
    </div>
  );
}

/** The empty-day body: the week ahead, who to call, and what the academy teaches. */
export function MyWeek({
  sessions,
  loading,
}: {
  sessions: readonly CoachScheduleEntry[];
  loading: boolean;
}) {
  const { data: academy } = useQuery({ queryKey: queryKeys.coach.academy(), queryFn: getCoachAcademy });
  const { data: profile } = useQuery({ queryKey: queryKeys.coach.profile(), queryFn: getCoachProfile });
  const tz = academy?.timezone;
  const week = classesThisWeek(sessions, tz);
  const later = week.length === 0 ? nextAfterWeek(sessions) : null;
  return (
    <div data-testid="my-week">
      <div className="mt-4">
        <LaneHeader title="My week" />
        {loading ? (
          <div className="space-y-2">
            <Skeleton variant="block" height={96} />
            <Skeleton variant="block" height={96} />
          </div>
        ) : week.length > 0 ? (
          <>
            <ul className="space-y-2">
              {week.map(({ entry, inDays }, i) => (
                <ClassCard
                  key={entry.occurrence_id}
                  entry={entry}
                  inDays={inDays}
                  tz={tz}
                  myUserId={profile?.user_id}
                  withButtons
                  testId={i === 0 ? "next-class" : undefined}
                />
              ))}
            </ul>
            <AllUpcoming />
          </>
        ) : later ? (
          <>
            <p className="mb-2 text-sm font-semibold">Your next class</p>
            <ul>
              <ClassCard entry={later} inDays={null} tz={tz} myUserId={profile?.user_id} withButtons testId="next-class" />
            </ul>
            <AllUpcoming />
          </>
        ) : (
          <EmptyState
            compact
            title="You have no classes yet."
            description={`${academy?.name ?? "The academy"} adds you to classes. When they do, you get a message here and the class appears on this screen. Nothing for you to do until then.`}
          />
        )}
      </div>
      <WhoToCall />
      <WhatWeTeachTeaser />
    </div>
  );
}

function nextAfterWeek(sessions: readonly CoachScheduleEntry[]): CoachScheduleEntry | null {
  const now = Date.now();
  return (
    [...sessions]
      .filter((s) => Date.parse(s.start_at) > now)
      .sort((a, b) => Date.parse(a.start_at) - Date.parse(b.start_at))[0] ?? null
  );
}

function AllUpcoming() {
  return (
    <Link
      href="/coach/sessions"
      className="mt-2 inline-flex min-h-touch items-center text-sm font-semibold text-rally-cobalt-700 underline-offset-2 hover:underline"
    >
      All upcoming classes →
    </Link>
  );
}
