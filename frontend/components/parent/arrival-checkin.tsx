"use client";

import { useMutation, useQueryClient } from "@tanstack/react-query";

import { Button } from "@/components/ds/button";
import {
  reportArrival,
  type ParentScheduleEntry,
  type ParentScheduleResponse,
} from "@/lib/api/parent";
import { arrivalFailure, parentArrivalView } from "@/lib/dropoff/checkin";

/**
 * "I've arrived" for one child's class date. State comes from the server
 * schedule, so "Waiting for staff" / "Checked in" survive a refresh. A failed
 * send says plainly that staff were NOT told, and Retry re-sends the same
 * idempotent request — nothing is ever queued and replayed later.
 */
export function ArrivalCheckin({
  studentId,
  childName,
  entry,
}: {
  studentId: string;
  childName: string;
  entry: ParentScheduleEntry;
}) {
  const queryClient = useQueryClient();
  const scheduleKey = ["parent", "child-schedule", studentId];
  const mutation = useMutation({
    mutationFn: () => reportArrival(studentId, entry.occurrence_id),
    // "online" (the default) would PAUSE this while offline and fire it when
    // the phone reconnects — a stale arrival. Fail now so the parent knows.
    networkMode: "always",
    retry: false,
    onSuccess: (checkin) => {
      queryClient.setQueryData<ParentScheduleResponse>(scheduleKey, (prev) =>
        prev
          ? {
              ...prev,
              entries: prev.entries.map((e) =>
                e.occurrence_id === entry.occurrence_id
                  ? { ...e, checkin, can_report_arrival: checkin.can_report_arrival }
                  : e,
              ),
            }
          : prev,
      );
    },
    // No refetch on error: the failure message (without Retry when retrying
    // cannot help) already replaces the button, and a refetch could drop the
    // row and the "NOT received" message with it.
  });

  const view = parentArrivalView(entry);
  const testId = `arrival-${studentId}-${entry.occurrence_id}`;

  // Before the "hidden" return: a refused send refetches the schedule, which
  // hides the row, and the "staff have NOT received" alert must outlive that.
  const failure = mutation.isError ? arrivalFailure(mutation.error) : null;
  if (failure && view !== "pending" && view !== "confirmed") {
    return (
      <div className="space-y-2">
        <p role="alert" data-testid={`${testId}-error`} className="text-sm font-semibold text-status-red-800">
          {failure.message}
        </p>
        {failure.retryable && (
          <Button
            variant="primary"
            size="lg"
            full
            data-testid={`${testId}-retry`}
            disabled={mutation.isPending}
            onClick={() => mutation.mutate()}
          >
            {mutation.isPending ? "Sending…" : "Retry"}
          </Button>
        )}
      </div>
    );
  }

  if (view === "confirmed") {
    return (
      <p role="status" data-testid={`${testId}-confirmed`} className="text-sm font-semibold text-status-green-800">
        Checked in
      </p>
    );
  }
  if (view === "pending") {
    return (
      <p role="status" data-testid={`${testId}-pending`} className="text-sm font-semibold text-rally-cobalt-700">
        Arrival sent · Waiting for staff
      </p>
    );
  }
  if (view === "expired") {
    return (
      <p role="status" data-testid={`${testId}-expired`} className="text-sm font-semibold text-status-red-800">
        Arrival not confirmed · Please tell a coach in person
      </p>
    );
  }
  if (view === "hidden") return null;

  return (
    <Button
      variant="primary"
      size="lg"
      full
      data-testid={`${testId}-report`}
      aria-label={`I've arrived with ${childName} for ${entry.session_title}`}
      disabled={mutation.isPending}
      onClick={() => mutation.mutate()}
    >
      {mutation.isPending ? "Sending…" : "I've arrived"}
    </Button>
  );
}
