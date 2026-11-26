"use client";

/**
 * S64: today's class dates as cards, the first thing on the admin dashboard
 * (spec docs/design/admin-today.md, D-20). Tapping a card opens its roster.
 * The phase chips come from the server clock, never the device clock.
 */

import Link from "next/link";
import type { Route } from "next";
import type { ReactNode } from "react";
import { useQuery } from "@tanstack/react-query";

import type { AdminToday, AdminTodayClass } from "@/lib/api/admin";
import { Chip } from "@/components/ds/chip";
import { EmptyState } from "@/components/ds/empty-state";
import { ErrorNotice } from "@/components/ds/error-notice";
import { LaneHeader } from "@/components/ds/lane";
import { Skeleton } from "@/components/ds/skeleton";

import { rosterHealthQuery } from "./health-query";
import { classClock, classTimeRange, countLine, healthNotesLabel, phaseChip } from "./format";

export function tomorrowLine(tomorrow: AdminToday["tomorrow"], timezone: string | null): string {
  if (tomorrow.class_count === 0 || !tomorrow.first_start_at) return "Nothing scheduled tomorrow.";
  const classes = tomorrow.class_count === 1 ? "1 class" : `${tomorrow.class_count} classes`;
  return `Tomorrow: ${classes}, first at ${classClock(tomorrow.first_start_at, timezone)}.`;
}

export function TodayClassesView({
  data,
  isLoading,
  isError,
  retrying = false,
  onRetry,
  onOpen,
  healthEnabled = true,
  renderHealth,
}: {
  data: AdminToday | undefined;
  isLoading: boolean;
  isError: boolean;
  retrying?: boolean;
  onRetry?: () => void;
  onOpen: (occurrenceId: string) => void;
  healthEnabled?: boolean;
  /** The per-card health count; injected so the view renders without a query client. */
  renderHealth?: (cls: AdminTodayClass) => ReactNode;
}) {
  const classes = data?.classes ?? [];
  return (
    <div data-testid="admin-today-classes">
      <LaneHeader
        title="Classes today"
        action={
          data ? (
            <span className="font-mono text-sm font-bold tabular-nums text-rally-ink">{classes.length}</span>
          ) : undefined
        }
      />
      {isLoading ? (
        <div className="grid gap-3 lg:grid-cols-3">
          {[0, 1, 2].map((i) => (
            <Skeleton key={i} variant="block" height="7rem" />
          ))}
        </div>
      ) : isError || !data ? (
        <ErrorNotice
          testId="admin-today-error"
          message="We could not load today's classes."
          onRetry={onRetry}
          retrying={retrying}
        />
      ) : classes.length === 0 ? (
        <EmptyState
          compact
          title="No classes today"
          description={tomorrowLine(data.tomorrow, data.timezone)}
          data-testid="admin-today-empty"
        />
      ) : (
        <>
          <ul role="list" className="grid gap-3 lg:grid-cols-3">
            {classes.map((cls) => (
              <li key={cls.occurrence_id}>
                <ClassCard
                  cls={cls}
                  timezone={data.timezone}
                  onOpen={onOpen}
                  health={healthEnabled && cls.phase !== "cancelled" ? renderHealth?.(cls) : null}
                />
              </li>
            ))}
          </ul>
          <Link
            href={"/admin/sessions" as Route}
            className="mt-3 inline-block text-sm text-rally-muted hover:text-rally-ink hover:underline"
            data-testid="admin-today-tomorrow"
          >
            {tomorrowLine(data.tomorrow, data.timezone)}
          </Link>
        </>
      )}
    </div>
  );
}

export function ClassCard({
  cls,
  timezone,
  onOpen,
  health,
}: {
  cls: AdminTodayClass;
  timezone: string | null;
  onOpen: (occurrenceId: string) => void;
  health?: ReactNode;
}) {
  const chip = phaseChip(cls);
  const time = classTimeRange(cls, timezone);
  const cancelled = cls.phase === "cancelled";
  const coach = cls.cover_coach_name ?? cls.coach_name;
  const facts = [coach ? `Coach ${coach}` : null, cls.location || null].filter(Boolean).join(" · ");
  const label = cancelled
    ? `${cls.title}, cancelled, ${time}. Open roster.`
    : `${cls.title}, ${chip.label.toLowerCase()}, ${time}, ${cls.enrolled_count} enrolled, ${cls.here_count} here. Open roster.`;
  return (
    <div
      className="h-full rounded-xl border border-rally-line bg-white transition hover:border-rally-cobalt"
      data-testid={`admin-today-class-${cls.occurrence_id}`}
    >
      <button
        type="button"
        onClick={() => onOpen(cls.occurrence_id)}
        aria-label={label}
        className="block w-full rounded-xl p-4 text-left focus:outline-none focus-visible:ring-2 focus-visible:ring-rally-cobalt"
      >
        <div className="flex flex-wrap items-center gap-x-3 gap-y-1">
          <Chip variant={chip.variant} label={chip.label} />
          <span className="text-[15px] font-semibold tabular-nums text-rally-ink">{time}</span>
        </div>
        <h3
          className={`mt-2 font-display text-[17px] font-semibold text-rally-ink ${cancelled ? "line-through" : ""}`}
        >
          {cls.title}
        </h3>
        {cancelled ? (
          cls.cancellation_reason ? (
            <p className="mt-1 text-[13px] text-rally-muted">{cls.cancellation_reason}</p>
          ) : null
        ) : (
          <>
            {facts ? <p className="mt-1 text-[13px] text-rally-muted">{facts}</p> : null}
            <p className="mt-1 text-[13px] text-rally-ink">{countLine(cls)}</p>
            {health}
          </>
        )}
      </button>
      {cls.cover_requested && !cancelled ? (
        <div className="flex flex-wrap items-center justify-between gap-2 border-t border-rally-line px-4 py-2">
          <Chip variant="pending" label="COACH CAN'T MAKE IT" />
          <Link
            href={`/admin?cover=${encodeURIComponent(cls.occurrence_id)}` as Route}
            className="text-sm font-semibold text-rally-cobalt hover:underline"
          >
            Find cover →
          </Link>
        </div>
      ) : null}
    </div>
  );
}

export function HealthCountLine({ count }: { count: number }) {
  if (count === 0) return null;
  return (
    <p className="mt-1 text-[13px] font-semibold text-status-red-800" data-testid="admin-today-health-count">
      <span aria-hidden="true">⚑ </span>
      {healthNotesLabel(count)}
    </p>
  );
}

/** Count only, shown once the read succeeds; nothing while loading or after a failure. */
export function LiveHealthCount({ occurrenceId }: { occurrenceId: string }) {
  const query = useQuery(rosterHealthQuery(occurrenceId));
  if (!query.isSuccess) return null;
  return <HealthCountLine count={query.data.declared_count} />;
}
