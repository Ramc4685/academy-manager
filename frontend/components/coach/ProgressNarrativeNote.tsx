"use client";

import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import {
  decideCoachNarrative,
  draftCoachNarrative,
  getCoachStudentNarrative,
  type CoachNarrative,
} from "@/lib/api/coach";
import { narrativeErrorCopy, narrativePanel } from "@/lib/coach/progress-narrative";
import { queryKeys } from "@/lib/query/keys";

/**
 * "Draft tonight's note": one model-drafted paragraph for the parents, shown
 * in a textarea the coach edits, then approves or rejects. Nothing reaches a
 * parent until Approve; the evening email falls back to its templated line.
 * The day's row is loaded on mount, so a pending draft survives a refresh.
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
  const [local, setLocal] = useState<CoachNarrative | null>(null);
  // The coach's edits; null means "show the row's text".
  const [edited, setEdited] = useState<string | null>(null);
  const loaded = useQuery({
    queryKey: queryKeys.coach.studentNarrative(studentId, date),
    queryFn: () => getCoachStudentNarrative(studentId, date),
    retry: false,
  });
  const invalidate = () => {
    void queryClient.invalidateQueries({ queryKey: queryKeys.coach.pendingNarratives(date) });
    void queryClient.invalidateQueries({
      queryKey: queryKeys.coach.studentNarrative(studentId, date),
    });
  };

  const draft = useMutation({
    mutationFn: () => draftCoachNarrative(studentId, date),
    onSuccess: (result) => {
      setLocal(result);
      setEdited(null);
      invalidate();
    },
  });
  const { panel, row } = narrativePanel(local, loaded.isError ? null : loaded.data);
  const text = edited ?? row?.text ?? "";
  const decide = useMutation({
    mutationFn: (status: "approved" | "rejected") =>
      decideCoachNarrative(row!.narrative_id, status === "approved" ? { status, text } : { status }),
    onSuccess: (result) => {
      setLocal(result);
      invalidate();
    },
  });

  const error = draft.error ?? decide.error;
  const inputId = `narrative-${studentId}`;
  const draftButton = (label: string) => (
    <button
      type="button"
      disabled={draft.isPending}
      onClick={() => draft.mutate()}
      className="min-h-touch text-sm font-bold text-rally-cobalt-700 disabled:opacity-50"
    >
      {draft.isPending ? "Drafting…" : label}
    </button>
  );
  const errorLine = error && (
    <p role="alert" className="text-sm text-red-700">
      {narrativeErrorCopy(error)}
    </p>
  );

  if (panel === "loading") return null;
  if (panel === "approved" || panel === "rejected") {
    return (
      <div className="mt-1.5 flex flex-wrap items-center justify-between gap-x-3 px-1">
        {panel === "approved" ? (
          <p className="text-xs font-semibold text-status-green-800">
            Note approved for tonight&apos;s email.
          </p>
        ) : (
          <p className="text-xs text-status-slate-600">
            Note rejected; tonight&apos;s email uses the standard line.
          </p>
        )}
        {draftButton("Draft again")}
        {errorLine}
      </div>
    );
  }
  if (panel === "draft") {
    return (
      <div className="mt-1.5 px-1">
        {draftButton(`Draft tonight's note for ${studentName}`)}
        {errorLine}
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
        onChange={(e) => setEdited(e.target.value)}
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
      {errorLine}
    </div>
  );
}
