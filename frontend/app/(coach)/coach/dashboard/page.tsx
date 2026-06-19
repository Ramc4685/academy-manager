"use client";

import { useState } from "react";
import Link from "next/link";
import { useQuery } from "@tanstack/react-query";

import {
  getCoachDayHub,
  type CoachDayHubSession,
  type CoachSkillGroup,
} from "@/lib/api/coach";
import { queryKeys } from "@/lib/query/keys";
import { formatSessionTimeRange } from "@/lib/time/session-time";

function localISO(offset = 0): string {
  const d = new Date();
  d.setDate(d.getDate() + offset);
  const year = d.getFullYear();
  const month = String(d.getMonth() + 1).padStart(2, "0");
  const day = String(d.getDate()).padStart(2, "0");
  return `${year}-${month}-${day}`;
}

function shiftDate(value: string, days: number): string {
  const [year, month, day] = value.split("-").map(Number);
  const d = new Date(year, month - 1, day);
  d.setDate(d.getDate() + days);
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}-${String(
    d.getDate(),
  ).padStart(2, "0")}`;
}

export default function CoachDashboardPage() {
  const [date, setDate] = useState(() => localISO());
  const [notice, setNotice] = useState<string | null>(null);
  const { data, isLoading, isError, refetch, isFetching } = useQuery({
    queryKey: queryKeys.coach.dayHub(date),
    queryFn: () => getCoachDayHub(date),
    staleTime: 2 * 60 * 1000,
  });

  const sessions = data?.sessions ?? [];

  return (
    <section data-testid="coach-day-hub" className="space-y-5">
      <header className="space-y-3">
        <div>
          <h1 className="font-display text-2xl font-semibold tracking-tight">
            Coach Day Hub
          </h1>
          <p className="mt-1 text-sm text-slate-500">
            Sessions, attendance, skill focus, and parent follow-up for the selected day.
          </p>
        </div>
        <DateControls date={date} onChange={setDate} />
      </header>

      {notice && (
        <p
          role="status"
          className="rounded-md border border-amber-200 bg-amber-50 p-3 text-sm text-amber-800"
        >
          {notice}
        </p>
      )}

      {isLoading && <HubSkeleton />}

      {isError && (
        <div
          role="alert"
          className="rounded-md border border-red-200 bg-red-50 p-4 text-sm text-red-800"
        >
          <p>Couldn&apos;t load the day hub. Try again.</p>
          <button
            onClick={() => void refetch()}
            className="mt-2 min-h-touch rounded-md border border-red-200 px-3"
          >
            Retry
          </button>
        </div>
      )}

      {data && (
        <div className="grid grid-cols-2 gap-3">
          <SummaryTile label="Sessions" value={data.summary.session_count} />
          <SummaryTile label="Students" value={data.summary.student_count} />
          <SummaryTile label="Skill focus" value={data.summary.skill_focus_count} />
          <SummaryTile label="Messages" value={data.summary.parent_message_count} />
        </div>
      )}

      {data && sessions.length === 0 && (
        <div className="rounded-lg border border-slate-200 bg-white p-4">
          <p className="font-medium text-slate-900">No sessions on this date.</p>
          <p className="mt-1 text-sm text-slate-500">
            Choose another day or open Sessions to scan the upcoming schedule.
          </p>
          <Link
            href="/coach/sessions"
            className="mt-3 inline-flex min-h-touch items-center rounded-md border border-slate-300 px-3 text-sm font-medium"
          >
            Open sessions
          </Link>
        </div>
      )}

      <ul className="space-y-3">
        {sessions.map((session) => (
          <SessionCard
            key={session.occurrence_id}
            session={session}
            date={date}
            onUnavailable={setNotice}
          />
        ))}
      </ul>

      {isFetching && !isLoading && (
        <p className="text-xs text-slate-400">Refreshing day hub...</p>
      )}
    </section>
  );
}

function DateControls({
  date,
  onChange,
}: {
  date: string;
  onChange: (value: string) => void;
}) {
  return (
    <div className="space-y-2">
      <div className="flex flex-wrap items-center gap-2">
        <button
          aria-label="Previous day"
          onClick={() => onChange(shiftDate(date, -1))}
          className="min-h-touch min-w-touch rounded-md border border-slate-300 px-3"
        >
          ‹
        </button>
        <button
          onClick={() => onChange(localISO())}
          className="min-h-touch rounded-md border border-slate-300 px-3 text-sm font-medium"
        >
          Today
        </button>
        <button
          onClick={() => onChange(localISO(1))}
          className="min-h-touch rounded-md border border-slate-300 px-3 text-sm font-medium"
        >
          Tomorrow
        </button>
        <Link
          href="/coach/sessions"
          className="inline-flex min-h-touch items-center rounded-md border border-slate-300 px-3 text-sm font-medium"
        >
          This week
        </Link>
        <button
          aria-label="Next day"
          onClick={() => onChange(shiftDate(date, 1))}
          className="min-h-touch min-w-touch rounded-md border border-slate-300 px-3"
        >
          ›
        </button>
      </div>
      <label className="block text-sm text-slate-500">
        <span className="sr-only">Selected date</span>
        <input
          type="date"
          value={date}
          onChange={(event) => onChange(event.target.value)}
          className="min-h-touch rounded-md border border-slate-300 bg-white px-3 text-sm text-slate-900"
        />
      </label>
    </div>
  );
}

function SummaryTile({ label, value }: { label: string; value: number }) {
  return (
    <div className="rounded-lg border border-slate-200 bg-white p-4">
      <p className="text-xs font-medium uppercase tracking-[0.12em] text-slate-500">
        {label}
      </p>
      <p className="mt-2 font-display text-3xl font-semibold text-slate-950">
        {value}
      </p>
    </div>
  );
}

function SessionCard({
  session,
  date,
  onUnavailable,
}: {
  session: CoachDayHubSession;
  date: string;
  onUnavailable: (message: string) => void;
}) {
  const sessionHref = `/coach/sessions/${encodeURIComponent(session.occurrence_id)}?date=${date}`;
  const skillsHref = `/coach/sessions/${encodeURIComponent(session.occurrence_id)}/skills?date=${date}`;
  const planHref = `/coach/today/plan?date=${date}`;

  return (
    <li className="rounded-lg border border-slate-200 bg-white p-4 shadow-sm">
      <div className="flex items-start justify-between gap-3">
        <div>
          <h2 className="font-semibold text-slate-950">{session.title}</h2>
          <p className="text-sm text-slate-500">{session.location}</p>
          <p className="mt-1 text-sm tabular-nums text-slate-600">
            {formatSessionTimeRange(session.start_at, session.end_at, session.timezone)}
          </p>
        </div>
        <p className="rounded-md bg-slate-100 px-2 py-1 text-xs font-medium text-slate-600">
          {session.roster.length} {session.roster.length === 1 ? "student" : "students"}
        </p>
      </div>

      <div className="mt-4">
        <p className="text-sm font-semibold text-slate-700">Grouped skill gaps</p>
        {session.skill_groups.length === 0 ? (
          <p className="mt-1 text-sm text-slate-500">No open skill focus for this session.</p>
        ) : (
          <ul className="mt-2 space-y-2">
            {session.skill_groups.slice(0, 4).map((group) => (
              <SkillGroupLine key={group.skill_id} group={group} />
            ))}
          </ul>
        )}
      </div>

      <div className="mt-4 grid grid-cols-2 gap-2">
        <ActionLink href={sessionHref} label="Open session" />
        <ActionLink href={planHref} label="Prepare" />
        <ActionLink href={skillsHref} label="Open skill updates" />
        <button
          onClick={() =>
            onUnavailable(
              "Parent messaging needs the coach-scoped messaging service before it can be used here.",
            )
          }
          className="min-h-touch rounded-md border border-slate-300 px-3 text-sm font-medium text-slate-700"
        >
          Message parents
        </button>
        <button
          onClick={() =>
            onUnavailable(
              "Absence notices need a coach-scoped replacement request workflow before they can be sent here.",
            )
          }
          className="col-span-2 min-h-touch rounded-md border border-slate-300 px-3 text-sm font-medium text-slate-700"
        >
          I can&apos;t attend
        </button>
      </div>
    </li>
  );
}

function SkillGroupLine({ group }: { group: CoachSkillGroup }) {
  return (
    <li className="rounded-md bg-slate-50 px-3 py-2">
      <p className="text-sm font-medium text-slate-800">{group.skill_name}</p>
      <p className="mt-0.5 text-xs text-slate-500">{group.student_names.join(", ")}</p>
    </li>
  );
}

function ActionLink({ href, label }: { href: string; label: string }) {
  return (
    <Link
      href={href as Parameters<typeof Link>[0]["href"]}
      className="inline-flex min-h-touch items-center justify-center rounded-md bg-blue-600 px-3 text-sm font-semibold text-white"
    >
      {label}
    </Link>
  );
}

function HubSkeleton() {
  return (
    <div className="space-y-3">
      <div className="grid grid-cols-2 gap-3">
        {[0, 1, 2, 3].map((item) => (
          <div key={item} className="h-24 animate-pulse rounded-lg bg-slate-100" />
        ))}
      </div>
      <div className="h-52 animate-pulse rounded-lg bg-slate-100" />
    </div>
  );
}
