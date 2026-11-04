"use client";

import { useEffect, useId, useRef, useState } from "react";
import type { Route } from "next";
import Link from "next/link";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { X } from "lucide-react";

import { Button, Chip, Overline, Skeleton } from "@/components/ds";
import { DialogError } from "@/components/ds/dialog-chrome";
import {
  correctStudentAttendance,
  fetchStudentCoachNotes,
  type CorrectableAttendanceStatus,
} from "@/lib/api/admin-families";
import { getAdminStudent } from "@/lib/api/v2/students";
import { lifecycleLabel, lifecycleVariant } from "@/lib/format/lifecycle-copy";
import { formatInstantDay } from "@/lib/money";
import { queryKeys } from "@/lib/query/keys";

import {
  attendanceStatusLabel,
  correctionConfirmCopy,
  correctionTargets,
  correctTriggerId,
  drawerAttendanceRows,
  type DrawerAttendanceRow,
  type OverviewChild,
} from "./family-record";

const FOCUSABLE =
  'a[href],button:not([disabled]),textarea:not([disabled]),input:not([disabled]),[tabindex]:not([tabindex="-1"])';

type Correction = {
  row: DrawerAttendanceRow;
  target: CorrectableAttendanceStatus | null;
  reason: string;
  step: "choose" | "confirm";
};

/**
 * People CRM spec §4 child drawer: a read-only view of one child with the
 * one action an admin needs here most, correcting a recent attendance mark.
 *
 * The Correct flow is two explicit steps (choose, then confirm), never a
 * select that commits on change, and after a save focus goes back to the
 * corrected row's Correct button, never to <body>. Hold child and Change
 * class are deferred; "Open full page" is the way to them for now.
 */
export function ChildDrawer({
  child,
  onClose,
}: {
  child: OverviewChild;
  onClose: () => void;
}) {
  const titleId = useId();
  const panelRef = useRef<HTMLDivElement | null>(null);
  const closeRef = useRef<HTMLButtonElement | null>(null);
  const queryClient = useQueryClient();
  const [correction, setCorrection] = useState<Correction | null>(null);
  const [focusAfterSave, setFocusAfterSave] = useState<string | null>(null);
  const [savedNote, setSavedNote] = useState<string | null>(null);

  const studentQuery = useQuery({
    queryKey: queryKeys.admin.studentDetail(child.studentId),
    queryFn: () => getAdminStudent(child.studentId),
  });
  const notesQuery = useQuery({
    queryKey: queryKeys.admin.studentCoachNotes(child.studentId),
    queryFn: () => fetchStudentCoachNotes(child.studentId),
  });

  const rows = drawerAttendanceRows(studentQuery.data?.recent_attendance ?? []);

  const save = useMutation({
    mutationFn: (c: Correction & { target: CorrectableAttendanceStatus }) =>
      correctStudentAttendance(c.row.occurrenceId ?? "", child.studentId, {
        status: c.target,
        reason: c.reason.trim() || null,
      }),
    onSuccess: async (result, c) => {
      await queryClient.invalidateQueries({
        queryKey: queryKeys.admin.studentDetail(child.studentId),
      });
      setSavedNote(
        `${c.row.dateLabel} changed from ${attendanceStatusLabel(
          result.previous_status,
        )} to ${attendanceStatusLabel(result.status)}.`,
      );
      setCorrection(null);
      setFocusAfterSave(correctTriggerId(c.row.occurrenceId ?? ""));
    },
  });

  // Open: focus the close button. Close (unmount): the page returns focus to
  // the child's row trigger.
  useEffect(() => {
    closeRef.current?.focus();
  }, []);

  // After a save, the rows re-render from the refetch; then focus the
  // corrected row's Correct button.
  useEffect(() => {
    if (!focusAfterSave || studentQuery.isFetching) return;
    const el = document.getElementById(focusAfterSave);
    if (el) {
      el.focus();
      setFocusAfterSave(null);
    }
  }, [focusAfterSave, studentQuery.isFetching, rows.length]);

  useEffect(() => {
    function onKeyDown(e: KeyboardEvent) {
      if (e.key === "Escape") {
        e.stopPropagation();
        if (correction) setCorrection(null);
        else onClose();
        return;
      }
      if (e.key !== "Tab") return;
      const panel = panelRef.current;
      if (!panel) return;
      const focusable = Array.from(panel.querySelectorAll<HTMLElement>(FOCUSABLE));
      if (focusable.length === 0) return;
      const first = focusable[0];
      const last = focusable[focusable.length - 1];
      if (e.shiftKey && document.activeElement === first) {
        e.preventDefault();
        last.focus();
      } else if (!e.shiftKey && document.activeElement === last) {
        e.preventDefault();
        first.focus();
      }
    }
    document.addEventListener("keydown", onKeyDown);
    return () => document.removeEventListener("keydown", onKeyDown);
  }, [correction, onClose]);

  const cancelCorrection = (row: DrawerAttendanceRow) => {
    setCorrection(null);
    // The Correct button re-renders once the inline form closes.
    setFocusAfterSave(correctTriggerId(row.occurrenceId ?? ""));
  };

  return (
    <div className="fixed inset-0 z-50 flex justify-end" data-testid="family-child-drawer-root">
      <button
        type="button"
        aria-label="Close child details"
        tabIndex={-1}
        className="absolute inset-0 bg-rally-ink/30"
        onClick={onClose}
      />
      <div
        ref={panelRef}
        role="dialog"
        aria-modal="true"
        aria-labelledby={titleId}
        data-testid="family-child-drawer"
        className="relative flex h-full w-full max-w-md flex-col overflow-y-auto bg-white shadow-xl"
      >
        <div className="flex items-start justify-between gap-3 border-b border-rally-line p-4">
          <div className="min-w-0">
            <Overline>Child</Overline>
            <h2
              id={titleId}
              className="mt-1 font-display text-xl font-semibold text-rally-ink"
              data-testid="family-child-drawer-name"
            >
              {child.name}
            </h2>
            {child.lifecycle && (
              <div className="mt-1">
                <Chip
                  variant={lifecycleVariant(child.lifecycle)}
                  label={lifecycleLabel(child.lifecycle, child.lifecycleAsOf)}
                />
              </div>
            )}
          </div>
          <button
            ref={closeRef}
            type="button"
            onClick={onClose}
            aria-label="Close"
            data-testid="family-child-drawer-close"
            className="inline-flex size-11 items-center justify-center rounded-md text-rally-muted hover:text-rally-ink focus:outline-none focus:ring-2 focus:ring-rally-cobalt-600"
          >
            <X className="size-5" aria-hidden="true" />
          </button>
        </div>

        <div className="space-y-5 p-4">
          <section>
            <Overline>Classes</Overline>
            {child.classes.length === 0 ? (
              <p className="mt-1 text-sm text-rally-muted">Not in a class right now.</p>
            ) : (
              <ul className="mt-1 space-y-1 text-sm text-rally-ink">
                {child.classes.map((title) => (
                  <li key={title}>{title}</li>
                ))}
              </ul>
            )}
          </section>

          <section aria-labelledby={`${titleId}-attendance`}>
            <h3 id={`${titleId}-attendance`}>
              <Overline>Recent attendance</Overline>
            </h3>
            {savedNote && (
              <p
                role="status"
                className="mt-1 text-sm text-rally-ink"
                data-testid="drawer-correction-saved"
              >
                {savedNote}
              </p>
            )}
            {studentQuery.isLoading ? (
              <Skeleton lines={3} />
            ) : studentQuery.isError ? (
              <p className="mt-1 text-sm text-rally-muted">Attendance could not be loaded.</p>
            ) : rows.length === 0 ? (
              <p className="mt-1 text-sm text-rally-muted">No attendance recorded yet.</p>
            ) : (
              <ul className="mt-2 divide-y divide-rally-line" data-testid="drawer-attendance">
                {rows.map((row) => {
                  const open = correction?.row.key === row.key ? correction : null;
                  return (
                    <li
                      key={row.key}
                      className="py-2"
                      data-testid={`drawer-attendance-row-${row.occurrenceId ?? row.key}`}
                    >
                      <div className="flex items-center justify-between gap-3">
                        <div className="min-w-0 text-sm">
                          <span className="font-medium text-rally-ink">{row.dateLabel}</span>{" "}
                          <span data-testid="drawer-attendance-status">{row.statusLabel}</span>
                          {row.correctedNote && (
                            <span className="ml-2 text-xs text-rally-muted">
                              ({row.correctedNote})
                            </span>
                          )}
                        </div>
                        {row.correctable && !open && (
                          <Button
                            size="sm"
                            variant="secondary"
                            id={correctTriggerId(row.occurrenceId ?? "")}
                            data-testid={correctTriggerId(row.occurrenceId ?? "")}
                            aria-label={`Correct ${row.dateLabel} mark (${row.statusLabel})`}
                            onClick={() => {
                              save.reset();
                              setSavedNote(null);
                              setCorrection({ row, target: null, reason: "", step: "choose" });
                            }}
                          >
                            Correct
                          </Button>
                        )}
                      </div>
                      {open && (
                        <CorrectionForm
                          childName={child.name}
                          correction={open}
                          pending={save.isPending}
                          error={save.error instanceof Error ? save.error.message : null}
                          onChange={setCorrection}
                          onCancel={() => cancelCorrection(row)}
                          onConfirm={() => {
                            if (open.target) save.mutate({ ...open, target: open.target });
                          }}
                        />
                      )}
                    </li>
                  );
                })}
              </ul>
            )}
          </section>

          <section aria-labelledby={`${titleId}-notes`}>
            <h3 id={`${titleId}-notes`}>
              <Overline>Coach notes</Overline>
            </h3>
            <p className="mt-1 text-xs text-rally-muted">
              Notes a coach shared with the family. Read-only.
            </p>
            {notesQuery.isLoading ? (
              <Skeleton lines={2} />
            ) : notesQuery.isError ? (
              <p className="mt-1 text-sm text-rally-muted">Coach notes could not be loaded.</p>
            ) : (notesQuery.data?.notes.length ?? 0) === 0 ? (
              <p className="mt-1 text-sm text-rally-muted" data-testid="drawer-notes-empty">
                No shared coach notes yet.
              </p>
            ) : (
              <ul className="mt-2 space-y-3" data-testid="drawer-coach-notes">
                {notesQuery.data?.notes.map((note) => (
                  <li key={note.note_id} className="rounded-lg border border-rally-line p-3">
                    <p className="whitespace-pre-line text-sm text-rally-ink">{note.body}</p>
                    <p className="mt-1 text-xs text-rally-muted">
                      {note.coach_name ?? "A coach"}
                      {note.session_title ? ` · ${note.session_title}` : ""} ·{" "}
                      {formatInstantDay(note.created_at)}
                    </p>
                  </li>
                ))}
              </ul>
            )}
          </section>

          <section className="border-t border-rally-line pt-4">
            <Link
              href={`/admin/students/${encodeURIComponent(child.studentId)}` as Route}
              data-testid="family-child-open-full-page"
              className="inline-flex min-h-11 items-center rounded-md px-1 text-sm font-semibold text-rally-cobalt-600 hover:underline focus:outline-none focus:ring-2 focus:ring-rally-cobalt-600"
            >
              Open full page
            </Link>
            <p className="mt-1 text-xs text-rally-muted">
              Hold, class changes and billing for this child are on the full page.
            </p>
          </section>
        </div>
      </div>
    </div>
  );
}

function CorrectionForm({
  childName,
  correction,
  pending,
  error,
  onChange,
  onCancel,
  onConfirm,
}: {
  childName: string;
  correction: Correction;
  pending: boolean;
  error: string | null;
  onChange: (next: Correction) => void;
  onCancel: () => void;
  onConfirm: () => void;
}) {
  const groupId = useId();
  const { row, target, reason, step } = correction;
  if (step === "confirm" && target) {
    return (
      <div
        className="mt-2 rounded-lg border border-rally-line bg-rally-paper p-3"
        data-testid="drawer-correction-confirm"
      >
        {error && <DialogError message={error} />}
        <p className="text-sm text-rally-ink" data-testid="drawer-correction-confirm-copy">
          {correctionConfirmCopy({ childName, dateLabel: row.dateLabel, from: row.status, to: target })}
        </p>
        <div className="mt-3 flex flex-wrap gap-2">
          <Button
            size="sm"
            variant="primary"
            disabled={pending}
            data-testid="drawer-correction-confirm-button"
            onClick={onConfirm}
          >
            {pending ? "Saving…" : `Change to ${attendanceStatusLabel(target)}`}
          </Button>
          <Button
            size="sm"
            variant="secondary"
            disabled={pending}
            onClick={() => onChange({ ...correction, step: "choose" })}
          >
            Back
          </Button>
        </div>
      </div>
    );
  }
  return (
    <div
      className="mt-2 rounded-lg border border-rally-line bg-rally-paper p-3"
      data-testid="drawer-correction-form"
    >
      <fieldset>
        <legend id={groupId} className="text-sm font-medium text-rally-ink">
          Correct {row.dateLabel} (now {row.statusLabel}) to
        </legend>
        <div className="mt-2 flex flex-wrap gap-3">
          {correctionTargets(row.status).map((status) => (
            <label key={status} className="inline-flex min-h-11 items-center gap-2 text-sm">
              <input
                type="radio"
                name={`correct-${row.key}`}
                value={status}
                checked={target === status}
                data-testid={`drawer-correction-target-${status}`}
                onChange={() => onChange({ ...correction, target: status })}
                className="size-4 accent-rally-cobalt-600"
              />
              {attendanceStatusLabel(status)}
            </label>
          ))}
        </div>
      </fieldset>
      <label className="mt-2 block text-sm text-rally-ink">
        Reason (optional)
        <textarea
          rows={2}
          value={reason}
          onChange={(e) => onChange({ ...correction, reason: e.target.value })}
          data-testid="drawer-correction-reason"
          className="mt-1 w-full rounded-md border border-rally-line bg-white px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-rally-cobalt-600/30"
        />
      </label>
      <div className="mt-3 flex flex-wrap gap-2">
        <Button
          size="sm"
          variant="primary"
          disabled={!target}
          data-testid="drawer-correction-review"
          onClick={() => onChange({ ...correction, step: "confirm" })}
        >
          Review change
        </Button>
        <Button size="sm" variant="secondary" onClick={onCancel}>
          Cancel
        </Button>
      </div>
    </div>
  );
}
