"use client";

/**
 * Stop all classes (issue #698): one date, one reason, one outcome, applied
 * to every active/held/paused enrollment for a student. Used from both the
 * student page and the family page — a per-student action, never rendered
 * on a session roster row.
 *
 * #696's shared `DepartureActions` surface is on a separate, unmerged
 * branch; per the departures design contract §5.3 this dialog is launched
 * directly from each page rather than depending on it.
 */
import { useState } from "react";
import { useMutation } from "@tanstack/react-query";
import { RefreshCw } from "lucide-react";

import {
  stopAllClasses,
  type StopAllClassesResponse,
  type DropDefaultOutcome,
} from "@/lib/api/v2/departure-policy";
import { Button } from "@/components/ds/button";
import { Modal } from "@/components/ds/modal";
import { OwnerOnlyHint, useIsOwner } from "@/components/admin/owner-context";

import {
  defaultOutcomeFor,
  isMoneyOutcomeAllowed,
  type MoneyOutcome,
} from "./stop-all-classes-outcome";

export function StopAllClassesDialog({
  studentId,
  studentName,
  policyDefaultOutcome,
  onClose,
  onDone,
}: {
  studentId: string;
  studentName: string;
  policyDefaultOutcome?: DropDefaultOutcome;
  onClose: () => void;
  onDone?: (result: StopAllClassesResponse) => void;
}) {
  const isOwner = useIsOwner();
  const [effectiveDate, setEffectiveDate] = useState(() => new Date().toISOString().slice(0, 10));
  const [reason, setReason] = useState("");
  const [outcome, setOutcome] = useState<MoneyOutcome>(() =>
    defaultOutcomeFor(policyDefaultOutcome),
  );
  const [result, setResult] = useState<StopAllClassesResponse | null>(null);

  const mutation = useMutation({
    mutationFn: () =>
      stopAllClasses(studentId, {
        effective_date: effectiveDate,
        outcome,
        reason,
      }),
    onSuccess: (data) => {
      setResult(data);
      onDone?.(data);
    },
  });

  if (result) {
    return (
      <Modal open title="Stop all classes" onClose={onClose}>
        <p className="text-sm text-rally-ink">
          {result.dropped_count} class{result.dropped_count === 1 ? "" : "es"} stopped for{" "}
          {studentName}.
        </p>
        {result.failed_count > 0 && (
          <div className="mt-3 rounded-md border border-rally-red-200 bg-rally-red-50 p-3 text-sm text-rally-red-900">
            <p className="font-medium">
              {result.failed_count} enrollment{result.failed_count === 1 ? "" : "s"} could not be
              stopped — nothing else was rolled back.
            </p>
            <ul className="mt-2 list-disc space-y-1 pl-4">
              {result.results
                .filter((r) => r.outcome === "failed")
                .map((r) => (
                  <li key={r.enrollment_id}>
                    {r.enrollment_id}: {r.error ?? "unknown error"}
                  </li>
                ))}
            </ul>
          </div>
        )}
        <div className="mt-4 flex justify-end">
          <Button size="sm" onClick={onClose}>
            Done
          </Button>
        </div>
      </Modal>
    );
  }

  return (
    <Modal open title={`Stop all classes for ${studentName}`} onClose={onClose}>
      {mutation.isError && (
        <p className="mb-3 text-sm text-rally-red-700">
          {mutation.error instanceof Error ? mutation.error.message : "Something went wrong."}
        </p>
      )}
      <div className="space-y-3">
        <label className="block text-sm">
          <span className="mb-1 block font-medium text-rally-ink">Effective date</span>
          <input
            type="date"
            value={effectiveDate}
            onChange={(event) => setEffectiveDate(event.target.value)}
            className="h-10 w-full rounded-md border border-neutral-200 bg-white px-3 text-sm text-rally-base outline-none focus:border-rally-cobalt-600 focus:ring-2 focus:ring-rally-cobalt-600/15"
          />
        </label>
        <label className="block text-sm">
          <span className="mb-1 block font-medium text-rally-ink">Outcome</span>
          <select
            value={outcome}
            onChange={(event) => setOutcome(event.target.value as MoneyOutcome)}
            className="h-10 w-full rounded-md border border-neutral-200 bg-white px-3 text-sm text-rally-base outline-none focus:border-rally-cobalt-600 focus:ring-2 focus:ring-rally-cobalt-600/15"
          >
            <option value="adjustment">No credit</option>
            <option value="credit" disabled={!isMoneyOutcomeAllowed("credit", isOwner)}>
              Credit {!isOwner ? "(owner only)" : ""}
            </option>
            <option value="refund" disabled={!isMoneyOutcomeAllowed("refund", isOwner)}>
              Refund {!isOwner ? "(owner only)" : ""}
            </option>
          </select>
          {!isOwner && outcome !== "adjustment" && (
            <span className="mt-1 inline-block">
              <OwnerOnlyHint />
            </span>
          )}
        </label>
        <label className="block text-sm">
          <span className="mb-1 block font-medium text-rally-ink">Reason</span>
          <textarea
            value={reason}
            onChange={(event) => setReason(event.target.value)}
            rows={2}
            className="w-full rounded-md border border-neutral-200 bg-white px-3 py-2 text-sm text-rally-base outline-none focus:border-rally-cobalt-600 focus:ring-2 focus:ring-rally-cobalt-600/15"
            placeholder="Why is this student leaving?"
          />
        </label>
      </div>
      <div className="mt-4 flex justify-end gap-2">
        <Button size="sm" variant="ghost" onClick={onClose} disabled={mutation.isPending}>
          Cancel
        </Button>
        <Button
          size="sm"
          disabled={
            !reason.trim() ||
            !effectiveDate ||
            !isMoneyOutcomeAllowed(outcome, isOwner) ||
            mutation.isPending
          }
          icon={mutation.isPending ? <RefreshCw className="size-3.5 animate-spin" /> : undefined}
          onClick={() => mutation.mutate()}
        >
          Stop all classes
        </Button>
      </div>
    </Modal>
  );
}
