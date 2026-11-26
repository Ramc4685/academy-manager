"use client";

import { useMutation, useQueryClient, type QueryClient } from "@tanstack/react-query";

import type { ToastOptions } from "@/components/ds/toast";
import { withdrawAbsenceNotice } from "@/lib/api/parent";
import { queryKeys } from "@/lib/query/keys";

export type AbsenceKey = { student_id: string; occurrence_id: string };

/** Every screen that shows an absence chip (S17): Children, Requests, Calendar, Home. */
export function invalidateAbsenceReaders(queryClient: QueryClient): void {
  void queryClient.invalidateQueries({ queryKey: queryKeys.parent.absences() });
  void queryClient.invalidateQueries({ queryKey: ["parent", "child-schedule"] });
  void queryClient.invalidateQueries({ queryKey: ["parent", "home"] });
  void queryClient.invalidateQueries({ queryKey: queryKeys.parent.calendar() });
}

/** S43: the success toast after reporting carries Undo (D-12). */
export function absenceReportedToast(onUndo: () => void): ToastOptions {
  return {
    kind: "success",
    title: "Absence reported",
    description: "The coach will see it.",
    durationMs: 8000,
    action: { label: "Undo", onClick: onUndo },
  };
}

/** Undo is offered only until class starts; the server enforces the same rule. */
export function canUndoAbsence(startAt: string | null | undefined, now: number = Date.now()): boolean {
  if (!startAt) return false;
  const start = Date.parse(startAt);
  return Number.isFinite(start) && start > now;
}

export function useWithdrawAbsence(onDone?: () => void) {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (key: AbsenceKey) => withdrawAbsenceNotice(key),
    meta: { success: { title: "Absence undone", description: "The class is back to normal." } },
    onSuccess: () => {
      onDone?.();
      invalidateAbsenceReaders(queryClient);
    },
  });
}
