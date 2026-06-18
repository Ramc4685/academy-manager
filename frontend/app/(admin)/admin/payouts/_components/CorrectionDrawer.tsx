"use client";
import { useState } from "react";
import { useMutation } from "@tanstack/react-query";
import { X } from "lucide-react";
import {
  updateOccurrenceCoachAttendance,
  updateSessionOccurrenceCoach,
  updateOccurrenceReplacement,
} from "@/lib/api/v2/sessions";

interface CorrectionDrawerProps {
  occurrenceId: string;
  scheduledCoachId: string;
  actualCoachId: string | null;
  attendanceStatus: "present" | "absent" | null;
  coaches: { id: string; name: string }[];
  onApplied: () => void;
  onClose: () => void;
}

export function CorrectionDrawer({
  occurrenceId,
  scheduledCoachId,
  actualCoachId,
  attendanceStatus,
  coaches,
  onApplied,
  onClose,
}: CorrectionDrawerProps) {
  const [coachId, setCoachId] = useState(actualCoachId ?? scheduledCoachId);
  const [coachReason, setCoachReason] = useState("");
  const [replacementId, setReplacementId] = useState("");
  const [replacementReason, setReplacementReason] = useState("");

  const canSubmitCoach = coachId !== "" && coachReason.trim().length > 0;

  const toggleAttendance = useMutation({
    mutationFn: (status: "present" | "absent") =>
      updateOccurrenceCoachAttendance(occurrenceId, {
        coach_id: actualCoachId ?? scheduledCoachId,
        status,
      }),
    onSuccess: onApplied,
  });

  const applyCoach = useMutation({
    mutationFn: () =>
      updateSessionOccurrenceCoach(occurrenceId, {
        actual_coach_id: coachId,
        reason: coachReason,
      }),
    onSuccess: () => {
      setCoachReason("");
      onApplied();
    },
  });

  const applyReplacement = useMutation({
    mutationFn: () =>
      updateOccurrenceReplacement(occurrenceId, {
        replacement_coach_id: replacementId || null,
        reason: replacementReason || null,
      }),
    onSuccess: onApplied,
  });
  const busy = toggleAttendance.isPending || applyCoach.isPending || applyReplacement.isPending;

  return (
    <div className="fixed inset-0 z-50" role="dialog" aria-modal="true" aria-labelledby="correction-drawer-title">
      <button
        type="button"
        aria-label="Close correction panel"
        className="absolute inset-0 cursor-default bg-rally-ink/35"
        onClick={onClose}
      />
      <aside className="absolute inset-y-0 right-0 flex w-[min(100vw,420px)] flex-col border-l border-rally-line bg-white shadow-2xl">
        <div className="flex items-start justify-between gap-4 border-b border-rally-line px-5 py-4">
          <div>
            <h3 id="correction-drawer-title" className="text-base font-semibold text-rally-ink">
              Correct occurrence
            </h3>
            <p className="mt-1 font-mono text-[11px] text-rally-muted">
              {occurrenceId}
            </p>
          </div>
          <button
            type="button"
            onClick={onClose}
            aria-label="Close"
            className="rounded-md p-2 text-rally-muted hover:bg-neutral-100 hover:text-rally-ink focus:outline-none focus:ring-2 focus:ring-rally-cobalt-600"
          >
            <X className="size-4" aria-hidden="true" />
          </button>
        </div>

        <div className="flex-1 space-y-6 overflow-y-auto px-5 py-5">
          <section className="space-y-3">
            <p className="font-mono text-[10px] font-bold uppercase tracking-overline text-rally-muted">
              Attendance
            </p>
            <div className="grid grid-cols-2 gap-2">
              {(["present", "absent"] as const).map((status) => {
                const selected = attendanceStatus === status;
                return (
                  <button
                    key={status}
                    type="button"
                    className={
                      selected
                        ? "rounded-md bg-rally-ink px-3 py-2 text-sm font-semibold capitalize text-white"
                        : "rounded-md border border-rally-line bg-white px-3 py-2 text-sm font-semibold capitalize text-rally-ink hover:bg-neutral-50"
                    }
                    disabled={busy}
                    onClick={() => toggleAttendance.mutate(status)}
                  >
                    {status}
                  </button>
                );
              })}
            </div>
          </section>

          <section className="space-y-3">
            <p className="font-mono text-[10px] font-bold uppercase tracking-overline text-rally-muted">
              Actual coach
            </p>
            <label className="grid gap-1.5 text-sm font-semibold text-rally-ink">
              Coach
              <select
                value={coachId}
                onChange={(e) => setCoachId(e.target.value)}
                className="h-10 w-full rounded-md border border-rally-line bg-white px-3 text-sm font-normal text-rally-ink outline-none focus:border-rally-cobalt-600 focus:ring-2 focus:ring-rally-cobalt-600/15"
              >
                {coaches.map((coach) => (
                  <option key={coach.id} value={coach.id}>
                    {coach.name}
                  </option>
                ))}
              </select>
            </label>
            <label className="grid gap-1.5 text-sm font-semibold text-rally-ink">
              Reason
              <input
                type="text"
                placeholder="Required for audit trail"
                value={coachReason}
                onChange={(e) => setCoachReason(e.target.value)}
                required
                className="h-10 w-full rounded-md border border-rally-line bg-white px-3 text-sm font-normal text-rally-ink outline-none focus:border-rally-cobalt-600 focus:ring-2 focus:ring-rally-cobalt-600/15"
              />
            </label>
            <button
              type="button"
              disabled={!canSubmitCoach || busy}
              onClick={() => applyCoach.mutate()}
              className="inline-flex min-h-10 items-center rounded-md border border-rally-line bg-white px-3 text-sm font-semibold text-rally-ink hover:bg-neutral-50 disabled:cursor-not-allowed disabled:opacity-50"
            >
              Apply coach change
            </button>
          </section>

          <section className="space-y-3">
            <p className="font-mono text-[10px] font-bold uppercase tracking-overline text-rally-muted">
              Replacement coach
            </p>
            <label className="grid gap-1.5 text-sm font-semibold text-rally-ink">
              Replacement
              <select
                value={replacementId}
                onChange={(e) => setReplacementId(e.target.value)}
                className="h-10 w-full rounded-md border border-rally-line bg-white px-3 text-sm font-normal text-rally-ink outline-none focus:border-rally-cobalt-600 focus:ring-2 focus:ring-rally-cobalt-600/15"
              >
                <option value="">No replacement</option>
                {coaches.map((coach) => (
                  <option key={coach.id} value={coach.id}>
                    {coach.name}
                  </option>
                ))}
              </select>
            </label>
            <label className="grid gap-1.5 text-sm font-semibold text-rally-ink">
              Reason
              <input
                type="text"
                placeholder="Optional"
                value={replacementReason}
                onChange={(e) => setReplacementReason(e.target.value)}
                className="h-10 w-full rounded-md border border-rally-line bg-white px-3 text-sm font-normal text-rally-ink outline-none focus:border-rally-cobalt-600 focus:ring-2 focus:ring-rally-cobalt-600/15"
              />
            </label>
            <button
              type="button"
              disabled={busy}
              onClick={() => applyReplacement.mutate()}
              className="inline-flex min-h-10 items-center rounded-md bg-rally-ink px-3 text-sm font-semibold text-white hover:bg-neutral-800 disabled:cursor-not-allowed disabled:opacity-50"
            >
              Set replacement
            </button>
          </section>
        </div>
      </aside>
    </div>
  );
}
