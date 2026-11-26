"use client";

import { useState } from "react";
import { useQuery } from "@tanstack/react-query";

import type { ApiError } from "@/lib/api/client";
import { getCoachRosterHealth, type CoachChildHealth, type CoachRosterHealth } from "@/lib/api/coach";
import { queryKeys } from "@/lib/query/keys";
import { useOnline } from "@/lib/pwa/online";

/**
 * S50 / D-14: a class date's health notes come from their own no-store read
 * (S49), are dropped as soon as nothing on screen uses them, and are never
 * persisted (shouldPersistQuery excludes "roster-health"). The roster itself
 * stays cached, so offline the roster paints and this area says why it is empty.
 */
export function coachRosterHealthQuery(occurrenceId: string) {
  return {
    queryKey: queryKeys.coach.rosterHealth(occurrenceId),
    queryFn: () => getCoachRosterHealth(occurrenceId),
    gcTime: 0,
    staleTime: 0,
    refetchOnWindowFocus: false,
    retry: false,
  } as const;
}

export type CoachHealthState =
  | { kind: "off" }
  | { kind: "offline" }
  | { kind: "loading" }
  | { kind: "error"; onRetry: () => void }
  | { kind: "ready"; data: CoachRosterHealth; byId: Map<string, CoachChildHealth> };

export function useCoachRosterHealth(
  occurrenceId: string | null | undefined,
  enabled = true,
): CoachHealthState {
  const online = useOnline();
  const query = useQuery({
    ...coachRosterHealthQuery(occurrenceId ?? ""),
    enabled: enabled && online && Boolean(occurrenceId),
  });
  if (!enabled || !occurrenceId) return { kind: "off" };
  if (!online) return { kind: "offline" };
  if (query.isSuccess) {
    return {
      kind: "ready",
      data: query.data,
      byId: new Map(query.data.children.map((child) => [child.student_id, child])),
    };
  }
  if (query.isError) {
    // 404: not a class this coach is on. Nothing to show, not an error.
    if ((query.error as ApiError).status === 404) return { kind: "off" };
    return { kind: "error", onRetry: () => void query.refetch() };
  }
  return { kind: "loading" };
}

export function healthNotesLabel(count: number): string {
  return `${count} health ${count === 1 ? "note" : "notes"}`;
}

/** The count strip on the class page, a Today tile and the plan. */
export function HealthStrip({
  state,
  testId = "health-strip",
  retry = true,
}: {
  state: CoachHealthState;
  testId?: string;
  /** False inside a link (a Today tile): no nested button. */
  retry?: boolean;
}) {
  if (state.kind === "offline") {
    return (
      <span data-testid={`${testId}-offline`} className="text-xs text-neutral-500">
        Health notes need a connection
      </span>
    );
  }
  if (state.kind === "error") {
    return (
      <span data-testid={`${testId}-error`} role="alert" className="text-xs text-red-700">
        Couldn&apos;t load health notes.
        {retry ? (
          <>
            {" "}
            <button type="button" className="underline" onClick={state.onRetry}>
              Try again
            </button>
          </>
        ) : null}
      </span>
    );
  }
  if (state.kind !== "ready" || state.data.declared_count === 0) return null;
  return (
    <span
      data-testid={testId}
      className="inline-flex items-center gap-1 rounded-full border border-red-200 bg-red-50 px-2 py-0.5 text-xs font-semibold text-red-800"
    >
      <span aria-hidden="true">●</span>
      {healthNotesLabel(state.data.declared_count)} in this class
    </span>
  );
}

/** Red marker on a roster row; tap to read the note and who to call. */
export function HealthMarker({
  child,
  initialOpen = false,
}: {
  child: CoachChildHealth | undefined;
  initialOpen?: boolean;
}) {
  const [open, setOpen] = useState(initialOpen);
  if (!child || child.status !== "declared") return null;
  return (
    <>
      <button
        type="button"
        data-testid={`health-marker-${child.student_id}`}
        aria-expanded={open}
        aria-label={`Health note for ${child.full_name}`}
        onClick={() => setOpen((v) => !v)}
        className="rounded-full border border-red-300 bg-red-50 px-2 py-0.5 text-xs font-semibold text-red-800"
      >
        ● Health
      </button>
      {open && (
        <div
          data-testid={`health-note-${child.student_id}`}
          className="w-full rounded-md border border-red-200 bg-red-50 px-3 py-2 text-sm text-red-900"
        >
          <p>{child.note}</p>
          {child.emergency_contact_name || child.emergency_contact_phone ? (
            <p className="mt-1 text-xs">
              Emergency contact: {child.emergency_contact_name}{" "}
              {child.emergency_contact_phone ? (
                <a className="underline" href={`tel:${child.emergency_contact_phone}`}>
                  {child.emergency_contact_phone}
                </a>
              ) : null}
            </p>
          ) : null}
          {child.parent_phone ? (
            <p className="mt-1 text-xs">
              Parent{child.parent_name ? ` (${child.parent_name})` : ""}:{" "}
              <a className="underline" href={`tel:${child.parent_phone}`}>
                {child.parent_phone}
              </a>
            </p>
          ) : null}
        </div>
      )}
    </>
  );
}

/** A Today tile's or plan section's own strip: one read per class date. */
export function ClassHealthStrip({
  occurrenceId,
  testId,
  retry,
}: {
  occurrenceId: string | null | undefined;
  testId?: string;
  retry?: boolean;
}) {
  return <HealthStrip state={useCoachRosterHealth(occurrenceId)} testId={testId} retry={retry} />;
}
