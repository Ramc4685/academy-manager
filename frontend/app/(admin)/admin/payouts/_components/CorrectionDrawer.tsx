"use client";
import { useState } from "react";
import { useMutation } from "@tanstack/react-query";
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

  return (
    <div className="fixed inset-y-0 right-0 z-40 w-80 bg-background shadow-xl border-l flex flex-col">
      <div className="flex items-center justify-between p-4 border-b">
        <h3 className="text-sm font-semibold">Correct occurrence</h3>
        <button onClick={onClose} aria-label="Close" className="text-muted-foreground hover:text-foreground">
          ✕
        </button>
      </div>

      <div className="flex-1 overflow-y-auto p-4 space-y-6">
        {/* Section A: Attendance */}
        <section>
          <p className="text-xs font-medium uppercase tracking-wide text-muted-foreground mb-2">
            Attendance
          </p>
          <div className="flex gap-2">
            {(["present", "absent"] as const).map((s) => (
              <button
                key={s}
                className={`rounded border px-3 py-1 text-sm capitalize ${
                  attendanceStatus === s ? "bg-primary text-primary-foreground" : ""
                }`}
                disabled={toggleAttendance.isPending}
                onClick={() => toggleAttendance.mutate(s)}
              >
                {s}
              </button>
            ))}
          </div>
        </section>

        {/* Section B: Actual coach */}
        <section>
          <p className="text-xs font-medium uppercase tracking-wide text-muted-foreground mb-2">
            Actual coach
          </p>
          <select
            value={coachId}
            onChange={(e) => setCoachId(e.target.value)}
            className="w-full rounded border px-2 py-1.5 text-sm mb-2"
          >
            {coaches.map((c) => (
              <option key={c.id} value={c.id}>
                {c.name}
              </option>
            ))}
          </select>
          <input
            type="text"
            placeholder="Reason (required)"
            value={coachReason}
            onChange={(e) => setCoachReason(e.target.value)}
            required
            aria-label="Reason for coach change"
            className="w-full rounded border px-2 py-1.5 text-sm mb-2"
          />
          <button
            disabled={!canSubmitCoach || applyCoach.isPending}
            onClick={() => applyCoach.mutate()}
            className="rounded border px-3 py-1.5 text-sm disabled:opacity-50"
          >
            Apply coach change
          </button>
        </section>

        {/* Section C: Replacement */}
        <section>
          <p className="text-xs font-medium uppercase tracking-wide text-muted-foreground mb-2">
            Replacement coach
          </p>
          <select
            value={replacementId}
            onChange={(e) => setReplacementId(e.target.value)}
            className="w-full rounded border px-2 py-1.5 text-sm mb-2"
          >
            <option value="">— none —</option>
            {coaches.map((c) => (
              <option key={c.id} value={c.id}>
                {c.name}
              </option>
            ))}
          </select>
          <input
            type="text"
            placeholder="Reason (optional)"
            value={replacementReason}
            onChange={(e) => setReplacementReason(e.target.value)}
            className="w-full rounded border px-2 py-1.5 text-sm mb-2"
          />
          <button
            disabled={applyReplacement.isPending}
            onClick={() => applyReplacement.mutate()}
            className="rounded border px-3 py-1.5 text-sm disabled:opacity-50"
          >
            Set replacement
          </button>
        </section>
      </div>
    </div>
  );
}
