"use client";

import { useState } from "react";
import { useMutation, useQueryClient } from "@tanstack/react-query";

import {
  decideCoachNarrative,
  draftCoachNarrative,
  type CoachNarrative,
} from "@/lib/api/coach";
import { narrativeErrorCopy } from "@/lib/coach/progress-narrative";
import { queryKeys } from "@/lib/query/keys";

/**
 * "Draft tonight's note": one model-drafted paragraph for the parents, shown
 * in a textarea the coach edits, then approves or rejects. Nothing reaches a
 * parent until Approve; the evening email falls back to its templated line.
 */
export function ProgressNarrativeNote({
  studentId,
  studentName,
  date,
}: {
  studentId: string;
  studentName: string;
  date: string;
}) {
  const queryClient = useQueryClient();
  const [row, setRow] = useState<CoachNarrative | null>(null);
  const [text, setText] = useState("");
  const invalidate = () =>
    queryClient.invalidateQueries({ queryKey: queryKeys.coach.pendingNarratives(date) });

  const draft = useMutation({
    mutationFn: () => draftCoachNarrative(studentId, date),
    onSuccess: (result) => {
      setRow(result);
      setText(result.text);
      void invalidate();
    },
  });
  const decide = useMutation({
    mutationFn: (status: "approved" | "rejected") =>
      decideCoachNarrative(row!.narrative_id, status === "approved" ? { status, text } : { status }),
    onSuccess: (result) => {
      setRow(result);
      void invalidate();
    },
  });

  const error = draft.error ?? decide.error;
  const inputId = `narrative-${studentId}`;

  if (row?.status === "approved") {
    return (
      <p className="mt-1.5 px-1 text-xs font-semibold text-status-green-800">
        Note approved for tonight&apos;s email.
      </p>
    );
  }
  if (row?.status === "rejected") {
    return (
      <p className="mt-1.5 px-1 text-xs text-status-slate-600">
        Note rejected; tonight&apos;s email uses the standard line.
      </p>
    );
  }
  if (!row) {
    return (
      <div className="mt-1.5 px-1">
        <button
          type="button"
          disabled={draft.isPending}
          onClick={() => draft.mutate()}
          className="min-h-touch text-sm font-bold text-rally-cobalt-700 disabled:opacity-50"
        >
          {draft.isPending ? "Drafting…" : `Draft tonight's note for ${studentName}`}
        </button>
        {error && (
          <p role="alert" className="text-sm text-red-700">
            {narrativeErrorCopy(error)}
          </p>
        )}
      </div>
    );
  }
  return (
    <div className="mt-1.5 space-y-1.5 px-1">
      <label htmlFor={inputId} className="block text-xs font-bold text-status-slate-600">
        AI draft for {studentName}&apos;s parents: edit, then approve
      </label>
      <textarea
        id={inputId}
        value={text}
        maxLength={500}
        rows={4}
        onChange={(e) => setText(e.target.value)}
        className="w-full rounded-md border-2 border-rally-line px-3 py-2 text-sm"
      />
      <div className="flex justify-end gap-1.5">
        <button
          type="button"
          disabled={decide.isPending}
          onClick={() => decide.mutate("rejected")}
          className="min-h-touch rounded-md border-2 border-rally-line px-3 text-sm font-bold disabled:opacity-50"
        >
          Reject
        </button>
        <button
          type="button"
          disabled={decide.isPending || text.trim().length === 0}
          onClick={() => decide.mutate("approved")}
          className="min-h-touch rounded-md bg-rally-cobalt-700 px-3 text-sm font-bold text-white disabled:opacity-50"
        >
          Approve
        </button>
      </div>
      {error && (
        <p role="alert" className="text-sm text-red-700">
          {narrativeErrorCopy(error)}
        </p>
      )}
    </div>
  );
}
