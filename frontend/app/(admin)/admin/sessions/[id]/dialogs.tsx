"use client";

import { useEffect, useRef, useState } from "react";
import { useMutation, useQuery } from "@tanstack/react-query";

import {
  createEnrollment,
  deleteEnrollment,
  listAdminSessions,
  previewWithdrawalCredit,
  quoteAdminEnrollment,
  bulkTransferEnrollments,
  transferEnrollment,
  withdrawEnrollment,
  type AdminEnrollmentQuote,
  type AdminEnrollmentView,
  type BulkTransferEnrollmentsResponse,
  type AdminSessionView,
  type AdminStudentView,
  type AdminUserView,
  type CreateEnrollmentRequest,
} from "@/lib/api/admin";
import { getDeparturePolicy } from "@/lib/api/v2/departure-policy";
import { queryKeys } from "@/lib/query/keys";
import {
  DEPARTURE_REASON_OPTIONS,
  type DepartureReasonCode,
} from "@/lib/admin/departure-reasons";
import {
  buildWithdrawRequest,
  initialWithdrawalOutcome,
  shouldDeferToPeriodEnd,
  withdrawErrorMessage,
  withdrawalOutcomeOptions,
  type WithdrawalOutcome,
} from "@/lib/admin/withdrawal";
import type { ApiError } from "@/lib/api/client";

import { useIsOwner } from "@/components/admin/owner-context";
import { StudentSearchPicker } from "@/components/admin/student-search-picker";
import { UnpricedEnrollAcknowledgement } from "@/components/admin/sessions/unpriced-class";
import { DEPARTURE_ACTION_DESCRIPTION } from "@/components/admin/enrollment/departure-actions";
import { Button } from "@/components/ds/button";
import { DialogActions, DialogError, Field, RallyModal as RallyDialog } from "@/components/ds/dialog-chrome";

import { formatCents, formatShortDateTime, inputClass, todayDateInput } from "./format";

export function AddToRosterDialog({
  open,
  onOpenChange,
  sessionId,
  onAdded,
  prefill,
  unpriced = false,
}: {
  open: boolean;
  onOpenChange: (v: boolean) => void;
  sessionId: string;
  onAdded: () => void;
  /** S10: the class has no fee yet; enrolling waits for an acknowledgement. */
  unpriced?: boolean;
  /**
   * Issue #827: seed the form with a student the admin already picked — the
   * Re-enroll action on a departed roster row. The dialog is otherwise
   * unchanged: the admin still sees and can change the student before the
   * POST, and the quote still re-prices for whoever is selected.
   */
  prefill?: Omit<CreateEnrollmentRequest, "session_id"> | null;
}) {
  const [form, setForm] = useState<Omit<CreateEnrollmentRequest, "session_id">>({
    student_id: "",
    parent_id: "",
    full_name: "",
  });
  // Re-seed each time the dialog is opened for a (different) student, so a
  // second Re-enroll never reopens on the first student's details.
  const seededFor = useRef<string | null>(null);
  useEffect(() => {
    if (!open) {
      seededFor.current = null;
      return;
    }
    const key = prefill?.student_id ?? "";
    if (seededFor.current === key) return;
    seededFor.current = key;
    setForm(prefill ?? { student_id: "", parent_id: "", full_name: "" });
  }, [open, prefill]);
  const [error, setError] = useState<string | null>(null);
  const [acknowledged, setAcknowledged] = useState(false);
  useEffect(() => {
    if (!open) setAcknowledged(false);
  }, [open]);
  const quoteQuery = useQuery<AdminEnrollmentQuote>({
    queryKey: ["admin", "enrollment-quote", sessionId, form.student_id],
    queryFn: () => quoteAdminEnrollment({ session_id: sessionId, student_id: form.student_id }),
    enabled: open && Boolean(form.student_id),
    staleTime: 30_000,
  });

  const mutation = useMutation({
    mutationFn: (payload: CreateEnrollmentRequest) => createEnrollment(payload),
    onSuccess: () => {
      setForm({ student_id: "", parent_id: "", full_name: "" });
      setError(null);
      onAdded();
    },
    onError: (err: Error) => setError(err.message ?? "Failed to enroll student."),
  });

  const handleSubmit = (e: React.FormEvent) => {
    e.preventDefault();
    mutation.mutate({ ...form, session_id: sessionId });
  };

  return (
    <RallyDialog
      open={open}
      onOpenChange={onOpenChange}
      title="Add to roster"
      description="Directly enroll a student into this session."
      overline="Roster"
    >
      {error && <DialogError message={error} />}
      {quoteQuery.data && (
        <p className="mb-3 rounded-md bg-blue-50 p-2 text-sm text-blue-800 dark:bg-blue-950 dark:text-blue-200">
          First month: {formatCents(quoteQuery.data.amount_due_cents)} ·{" "}
          {quoteQuery.data.formula} — the monthly rate covers 4 classes per weekly meeting; any
          extra class in the month is free.
          {quoteQuery.data.quote_expires_at
            ? ` Quote expires ${formatShortDateTime(quoteQuery.data.quote_expires_at)}.`
            : ""}
        </p>
      )}
      <form onSubmit={handleSubmit} className="space-y-3">
        <Field label="Student" required>
          <StudentSearchPicker
            enabled={open}
            value={form.student_id}
            selected={form.student_id ? form : undefined}
            selectClassName={inputClass}
            onChange={(student) =>
              setForm({
                student_id: student.student_id,
                parent_id: student.parent_id,
                full_name: student.full_name,
              })
            }
          />
        </Field>
        {unpriced && (
          <UnpricedEnrollAcknowledgement checked={acknowledged} onChange={setAcknowledged} />
        )}
        <DialogActions>
          <Button variant="secondary" size="sm" type="button" onClick={() => onOpenChange(false)}>
            Cancel
          </Button>
          <Button
            variant="primary"
            size="sm"
            type="submit"
            disabled={mutation.isPending || (unpriced && !acknowledged)}
          >
            {mutation.isPending ? "Enrolling…" : "Enroll"}
          </Button>
        </DialogActions>
      </form>
    </RallyDialog>
  );
}

/** A0-8: "Ana could not move: Target session full" lines for a bulk result. */
export function bulkTransferFailures(
  result: BulkTransferEnrollmentsResponse,
  enrollments: Pick<AdminEnrollmentView, "enrollment_id" | "full_name">[],
): string[] {
  const names = new Map(enrollments.map((e) => [e.enrollment_id, e.full_name]));
  return result.results
    .filter((row) => !row.ok)
    .map(
      (row) =>
        `${names.get(row.enrollment_id) ?? "A student"} could not move: ${row.message ?? "refused"}`,
    );
}

/** Transfer one roster row, or several at once (A0-8) to the same class. */
export function TransferEnrollmentDialog({
  enrollments,
  currentSessionId,
  currentSessionTitle,
  onClose,
  onMoved,
}: {
  enrollments: AdminEnrollmentView[];
  currentSessionId: string;
  currentSessionTitle: string;
  onClose: () => void;
  /** `close` is false when some rows of a bulk move were refused: the roster
   * refreshes but the dialog stays open to say which ones and why. */
  onMoved: (close: boolean) => void;
}) {
  const open = enrollments.length > 0;
  const bulk = enrollments.length > 1;
  const [failures, setFailures] = useState<string[]>([]);
  const [targetSessionId, setTargetSessionId] = useState("");
  const [effectiveDate, setEffectiveDate] = useState(todayDateInput());
  const [reason, setReason] = useState("");
  const [error, setError] = useState<string | null>(null);
  // Fetch all upcoming sessions (next 30 days) so the dropdown isn't
  // limited to today's two slots — moving a student to a different weekly
  // class only makes sense if the user can actually see those other classes.
  const sessionsQuery = useQuery({
    queryKey: ["admin", "sessions", "upcoming"] as const,
    queryFn: () => listAdminSessions(undefined, { window: "upcoming" }),
    enabled: open,
  });
  // Dedupe by title: each weekly class shows up many times across the
  // window (one per dated instance); show one row per distinct class
  // with the soonest start_at as its value.
  const candidateSessions = (() => {
    const all = sessionsQuery.data?.sessions ?? [];
    // Exclude the current session AND any other dated instance that
    // shares the same weekly title — the user can't meaningfully "move"
    // a student to a future instance of the class they're already in.
    const otherClasses = all.filter(
      (s) =>
        s.session_id !== currentSessionId &&
        (currentSessionTitle === "" || s.title !== currentSessionTitle),
    );
    const byTitle = new Map<string, AdminSessionView>();
    for (const s of otherClasses) {
      const prev = byTitle.get(s.title);
      if (!prev || new Date(s.start_at).getTime() < new Date(prev.start_at).getTime()) {
        byTitle.set(s.title, s);
      }
    }
    return Array.from(byTitle.values()).sort((a, b) =>
      a.title.localeCompare(b.title),
    );
  })();
  const mutation = useMutation({
    mutationFn: async (): Promise<string[]> => {
      const payload = {
        target_session_id: targetSessionId,
        effective_date: effectiveDate,
        reason: reason || undefined,
      };
      if (!bulk) {
        await transferEnrollment(enrollments[0].enrollment_id, payload);
        return [];
      }
      const result = await bulkTransferEnrollments({
        ...payload,
        enrollment_ids: enrollments.map((e) => e.enrollment_id),
      });
      return bulkTransferFailures(result, enrollments);
    },
    onSuccess: (refused) => {
      setError(null);
      setFailures(refused);
      if (refused.length > 0) {
        onMoved(false);
        return;
      }
      setTargetSessionId("");
      setEffectiveDate(todayDateInput());
      setReason("");
      onMoved(true);
    },
    onError: (err: Error) => setError(err.message ?? "Failed to move enrollment."),
  });

  return (
    <RallyDialog
      open={open}
      onOpenChange={(next) => {
        if (next) return;
        setFailures([]);
        onClose();
      }}
      title={bulk ? `Transfer ${enrollments.length} students` : "Transfer enrollment"}
      description={
        bulk
          ? `Transfer ${enrollments.map((e) => e.full_name).join(", ")} to another session.`
          : open
            ? `Transfer ${enrollments[0].full_name} to another session.`
            : ""
      }
      overline="Transfer"
    >
      {error && <DialogError message={error} />}
      {failures.length > 0 && (
        <div
          role="alert"
          data-testid="bulk-transfer-failures"
          className="mb-3 rounded-md border border-amber-200 bg-amber-50 p-3 text-sm text-amber-900"
        >
          <p className="font-semibold">The others moved. Check these students:</p>
          <ul className="mt-1 list-disc pl-5">
            {failures.map((line) => (
              <li key={line}>{line}</li>
            ))}
          </ul>
        </div>
      )}
      {failures.length > 0 ? (
        // The moved rows are gone from this class: resubmitting would move them again.
        <DialogActions>
          <Button
            variant="primary"
            size="sm"
            type="button"
            onClick={() => {
              setFailures([]);
              onClose();
            }}
          >
            Done
          </Button>
        </DialogActions>
      ) : (
      <form
        className="space-y-3"
        onSubmit={(event) => {
          event.preventDefault();
          mutation.mutate();
        }}
      >
        <Field label="Target session" required>
          <RallySessionPicker
            sessions={candidateSessions}
            value={targetSessionId}
            onChange={setTargetSessionId}
            loading={sessionsQuery.isLoading}
          />
        </Field>
        <Field label="Effective date" required>
          <input
            type="date"
            required
            value={effectiveDate}
            onChange={(event) => setEffectiveDate(event.target.value)}
            className={inputClass}
          />
        </Field>
        <Field label="Reason">
          <input
            value={reason}
            onChange={(event) => setReason(event.target.value)}
            className={inputClass}
            placeholder="Optional"
          />
        </Field>
        <p className="text-xs text-rally-subtle">
          Transferring reserves a seat in the target class first, then releases this seat.
          Billing follows the new class&apos;s price from the effective date — the current
          period&apos;s invoice is adjusted, it is not charged again.
        </p>
        <p className="text-xs text-rally-subtle">{DEPARTURE_ACTION_DESCRIPTION.transfer}</p>
        <DialogActions>
          <Button
            variant="secondary"
            size="sm"
            type="button"
            onClick={() => {
              setFailures([]);
              onClose();
            }}
          >
            Cancel
          </Button>
          <Button
            variant="primary"
            size="sm"
            type="submit"
            disabled={
              mutation.isPending ||
              candidateSessions.length === 0 ||
              !targetSessionId ||
              !effectiveDate
            }
          >
            {mutation.isPending ? "Transferring…" : "Transfer"}
          </Button>
        </DialogActions>
      </form>
      )}
    </RallyDialog>
  );
}

// Rally-styled session picker — replaces native <select> whose OS dropdown
// renders as a giant unstyled overlay on macOS Chrome. Click the button to
// toggle an absolute-positioned options list constrained to the dialog.
export function RallySessionPicker({
  sessions,
  value,
  onChange,
  loading,
}: {
  sessions: AdminSessionView[];
  value: string;
  onChange: (sessionId: string) => void;
  loading: boolean;
}) {
  const [open, setOpen] = useState(false);
  const selected = sessions.find((s) => s.session_id === value);
  const formatTime = (s: AdminSessionView) =>
    new Date(s.start_at).toLocaleTimeString([], { hour: "numeric", minute: "2-digit" });
  return (
    <div className="relative">
      <button
        type="button"
        onClick={() => !loading && setOpen((o) => !o)}
        disabled={loading}
        className="w-full flex items-center justify-between gap-2 rounded-md border border-rally-line bg-white px-3 py-2 text-left text-sm focus:outline-none focus:ring-2 focus:ring-rally-cobalt-600/30 disabled:opacity-60"
      >
        <span className={selected ? "text-rally-ink" : "text-rally-muted"}>
          {loading
            ? "Loading sessions…"
            : selected
              ? `${selected.title} — ${formatTime(selected)}`
              : sessions.length === 0
                ? "No other upcoming sessions"
                : "Select session"}
        </span>
        <span className="font-mono text-xs text-rally-muted">{open ? "▴" : "▾"}</span>
      </button>
      {open && sessions.length > 0 && (
        <ul
          role="listbox"
          className="absolute left-0 right-0 z-20 mt-1 max-h-64 overflow-y-auto rounded-md border border-rally-line bg-white shadow-lg"
        >
          {sessions.map((s) => {
            const isSelected = s.session_id === value;
            return (
              <li key={s.session_id} role="option" aria-selected={isSelected}>
                <button
                  type="button"
                  onClick={() => {
                    onChange(s.session_id);
                    setOpen(false);
                  }}
                  className="w-full px-3 py-2 text-left text-sm hover:bg-rally-paper"
                  style={{
                    background: isSelected ? "var(--rally-cobalt-soft)" : "transparent",
                    color: isSelected ? "var(--rally-cobalt)" : "var(--rally-ink)",
                    fontWeight: isSelected ? 600 : 500,
                  }}
                >
                  <span className="block">{s.title}</span>
                  <span className="block font-mono text-[11px] text-rally-muted">
                    next class: {new Date(s.start_at).toLocaleDateString()} · {formatTime(s)}
                  </span>
                </button>
              </li>
            );
          })}
        </ul>
      )}
    </div>
  );
}

// ─────────────────────────────────────────────────────────────────────────────
// Shared helpers
// ─────────────────────────────────────────────────────────────────────────────

export function WithdrawalCreditDialog({
  enrollment,
  onClose,
  onApproved,
}: {
  enrollment: AdminEnrollmentView | null;
  onClose: () => void;
  onApproved: () => void;
}) {
  // Issue #670: one withdraw path. The backend issues the credit itself for
  // `outcome: "credit"` and refuses that outcome to non-owners, so the option
  // is disabled here for plain admins instead of failing on submit.
  const isOwner = useIsOwner();
  const outcomeOptions = withdrawalOutcomeOptions(isOwner);
  // Issue #742: this dialog used to open on credit/refund by role and ignore
  // the academy's configured `drop_default_outcome` entirely, unlike Stop all
  // classes. Same query key as the settings panel and the student page, so
  // this is a cache read, not an extra request per roster row.
  const departurePolicyQuery = useQuery({
    queryKey: queryKeys.admin.departurePolicy(),
    queryFn: getDeparturePolicy,
  });
  const [withdrawalDate, setWithdrawalDate] = useState(todayDateInput);
  // `null` = the admin has not overridden the policy default. Derived rather
  // than seeded into state because the policy arrives after the first render.
  const [chosenOutcome, setChosenOutcome] = useState<WithdrawalOutcome | null>(null);
  const outcome =
    chosenOutcome ??
    initialWithdrawalOutcome(departurePolicyQuery.data?.drop_default_outcome, isOwner);
  // Issue #820: the TIMING half of the same policy value. `no_credit_end_of_period`
  // schedules the drop for the academy-local month end rather than performing it
  // on the date below, which the backend then ignores.
  const deferToPeriodEnd = shouldDeferToPeriodEnd(
    departurePolicyQuery.data?.drop_default_outcome,
  );
  const [adminNote, setAdminNote] = useState("");
  // Issue #775: the structured half of the departure reason. Optional, and
  // opens on "not specified" — a pre-selected code would be recorded on
  // every Drop where the admin simply did not look at the field.
  const [reasonCode, setReasonCode] = useState<DepartureReasonCode | "">("");
  const [error, setError] = useState<string | null>(null);
  const previewMutation = useMutation({
    mutationFn: () =>
      previewWithdrawalCredit(enrollment!.enrollment_id, {
        withdrawal_date: `${withdrawalDate}T00:00:00.000Z`,
      }),
    onError: (err: Error) => setError(err.message ?? "Could not preview credit."),
  });
  const approveMutation = useMutation({
    mutationFn: () =>
      withdrawEnrollment(
        enrollment!.enrollment_id,
        buildWithdrawRequest({
          withdrawalDate,
          outcome,
          adminNote,
          ...(reasonCode ? { reasonCode } : {}),
          deferToPeriodEnd,
        }),
      ),
    onSuccess: () => {
      setChosenOutcome(null);
      setAdminNote("");
      setReasonCode("");
      setError(null);
      onApproved();
    },
    onError: (err: ApiError) => setError(withdrawErrorMessage(err)),
  });
  const preview = previewMutation.data;
  return (
    <RallyDialog
      open={enrollment !== null}
      onOpenChange={(open) => {
        if (open) return;
        // Drop the admin's override so the next Drop opens on the academy's
        // configured default again rather than the last row's choice (#742).
        setChosenOutcome(null);
        onClose();
      }}
      // Title/labels use the "Drop" vocabulary to match the launcher (the
      // shared DepartureActions menu) — one word for one action across the
      // interface. e2e/specs/admin-enrollment-withdraw.spec.ts asserts on
      // this dialog's accessible name; keep the two in sync.
      title="Drop enrollment"
      description={
        enrollment
          ? `Drop ${enrollment.full_name} — releases the seat, stops autopay, and settles unused-class credit per the outcome below.`
          : ""
      }
      overline="Lifecycle"
    >
      {error && <DialogError message={error} />}
      <div className="space-y-3">
        <Field label="Outcome" required>
          <select
            value={outcome}
            onChange={(event) => {
              setChosenOutcome(event.target.value as WithdrawalOutcome);
              previewMutation.reset();
            }}
            className={inputClass}
          >
            {outcomeOptions.map((option) => (
              <option
                key={option.value}
                value={option.value}
                disabled={option.disabledReason !== undefined}
              >
                {option.label}
              </option>
            ))}
          </select>
        </Field>
        {outcomeOptions.some((option) => option.disabledReason) && (
          <p className="text-xs text-neutral-500">
            {outcomeOptions.find((option) => option.disabledReason)?.disabledReason}
          </p>
        )}
        {deferToPeriodEnd ? (
          <p
            data-testid="withdraw-defer-notice"
            className="rounded-md bg-neutral-50 p-3 text-sm text-neutral-600 dark:bg-neutral-800 dark:text-neutral-300"
          >
            This academy drops at the end of the billing period. The student keeps
            their place and their seat until the last day of this month, and the drop
            is applied automatically then. You can call it off until it runs.
          </p>
        ) : (
          <Field label="Drop date" required>
            <input
              type="date"
              required
              value={withdrawalDate}
              onChange={(event) => {
                setWithdrawalDate(event.target.value);
                previewMutation.reset();
              }}
              className={inputClass}
            />
          </Field>
        )}
        {outcome === "credit" && (
          <button
            type="button"
            disabled={!withdrawalDate || previewMutation.isPending}
            onClick={() => previewMutation.mutate()}
            className="min-h-touch rounded-md border border-blue-300 px-3 text-sm font-medium text-blue-700 hover:bg-blue-50 disabled:opacity-60 dark:border-blue-700 dark:text-blue-300"
          >
            {previewMutation.isPending ? "Previewing..." : "Preview credit"}
          </button>
        )}
        {preview && (
          <div className="rounded-md bg-neutral-50 p-3 text-sm dark:bg-neutral-800">
            <p className="font-medium">Credit: {preview.display_amount}</p>
            <p className="mt-1 text-neutral-500">
              {preview.unused_classes} of {preview.total_classes} unused classes.
            </p>
            <p className="mt-1 text-xs text-neutral-500">{preview.message}</p>
          </div>
        )}
        <Field label="Reason code">
          <select
            value={reasonCode}
            data-testid="withdraw-reason-code"
            onChange={(event) =>
              setReasonCode(event.target.value as DepartureReasonCode | "")
            }
            className={inputClass}
          >
            <option value="">Not specified</option>
            {DEPARTURE_REASON_OPTIONS.map((option) => (
              <option key={option.value} value={option.value}>
                {option.label}
              </option>
            ))}
          </select>
          <p className="mt-1 text-xs text-neutral-500">
            Groups this departure in the leaving report. The note still says the rest.
          </p>
        </Field>
        <Field label="Admin note">
          <textarea
            value={adminNote}
            onChange={(event) => setAdminNote(event.target.value)}
            rows={3}
            className={inputClass}
          />
        </Field>
        <p className="text-xs text-rally-subtle">{DEPARTURE_ACTION_DESCRIPTION.drop}</p>
        <DialogActions>
          <Button variant="secondary" size="sm" type="button" onClick={onClose}>
            Cancel
          </Button>
          <Button
            variant="danger"
            size="sm"
            type="button"
            disabled={
              !withdrawalDate ||
              approveMutation.isPending ||
              (outcome === "credit" && !preview)
            }
            onClick={() => approveMutation.mutate()}
          >
            {approveMutation.isPending ? "Saving..." : "Drop"}
          </Button>
        </DialogActions>
      </div>
    </RallyDialog>
  );
}

export function RemoveEnrollmentDialog({
  enrollment,
  onClose,
  onRemoved,
}: {
  enrollment: AdminEnrollmentView | null;
  onClose: () => void;
  onRemoved: () => void;
}) {
  const [effectiveDate, setEffectiveDate] = useState(todayDateInput);
  const [reason, setReason] = useState("");
  const [error, setError] = useState<string | null>(null);
  const mutation = useMutation({
    mutationFn: () =>
      deleteEnrollment(enrollment!.enrollment_id, {
        effective_date: effectiveDate,
        reason,
      }),
    onSuccess: () => {
      setEffectiveDate(todayDateInput());
      setReason("");
      setError(null);
      onRemoved();
    },
    onError: (err: Error) => setError(err.message ?? "Could not remove enrollment."),
  });

  return (
    <RallyDialog
      open={enrollment !== null}
      onOpenChange={(open) => !open && onClose()}
      title="Delete enrollment"
      description={enrollment ? `Delete ${enrollment.full_name}'s enrollment.` : ""}
      overline="Lifecycle"
    >
      {error && <DialogError message={error} />}
      <form
        className="space-y-3"
        onSubmit={(event) => {
          event.preventDefault();
          mutation.mutate();
        }}
      >
        <Field label="Effective date" required>
          <input
            type="date"
            required
            value={effectiveDate}
            onChange={(event) => setEffectiveDate(event.target.value)}
            className={inputClass}
          />
        </Field>
        <Field label="Reason" required>
          <textarea
            required
            value={reason}
            onChange={(event) => setReason(event.target.value)}
            rows={3}
            className={inputClass}
          />
        </Field>
        <p className="text-xs text-rally-subtle">
          Deleting ends this enrollment as of the effective date, releases the seat if it holds
          one, voids future unpaid invoices and turns off autopay for this enrollment. No credit
          is issued — there is no outcome choice here, unlike Drop.
        </p>
        <p className="text-xs text-rally-subtle">{DEPARTURE_ACTION_DESCRIPTION.delete}</p>
        <DialogActions>
          <Button variant="secondary" size="sm" type="button" onClick={onClose}>
            Cancel
          </Button>
          <Button
            variant="danger"
            size="sm"
            type="submit"
            disabled={!effectiveDate || !reason.trim() || mutation.isPending}
          >
            {mutation.isPending ? "Deleting..." : "Delete"}
          </Button>
        </DialogActions>
      </form>
    </RallyDialog>
  );
}

export function CoachSelect({
  coaches,
  value,
  onChange,
  allowEmpty = false,
  emptyLabel = "Select coach",
}: {
  coaches: AdminUserView[];
  value: string;
  onChange: (coachId: string) => void;
  allowEmpty?: boolean;
  emptyLabel?: string;
}) {
  return (
    <select
      required={!allowEmpty}
      value={value}
      onChange={(event) => onChange(event.target.value)}
      className={inputClass}
    >
      <option value="">{emptyLabel}</option>
      {coaches.map((coach) => (
        <option key={coach.user_id} value={coach.user_id}>
          {coach.display_name} ({coach.email})
        </option>
      ))}
    </select>
  );
}
