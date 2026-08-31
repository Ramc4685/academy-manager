"use client";

import { useState } from "react";
import { useMutation, useQuery } from "@tanstack/react-query";
import * as Dialog from "@radix-ui/react-dialog";

import {
  approveWithdrawalCredit,
  createEnrollment,
  deleteEnrollment,
  listAdminSessions,
  listAdminStudents,
  pauseEnrollment,
  previewWithdrawalCredit,
  quoteAdminEnrollment,
  transferEnrollment,
  withdrawEnrollment,
  type AdminEnrollmentQuote,
  type AdminEnrollmentView,
  type AdminSessionView,
  type AdminStudentView,
  type AdminUserView,
  type CreateEnrollmentRequest,
} from "@/lib/api/admin";
import { queryKeys } from "@/lib/query/keys";

import { Button } from "@/components/ds/button";
import { DialogActions, DialogError, Field, RallyModal as RallyDialog } from "@/components/ds/dialog-chrome";

import { dateInputValueFromOffset, formatCents, formatShortDateTime, inputClass, todayDateInput } from "./format";

const DAYS_OF_WEEK = [
  { value: "Mon", label: "Monday" },
  { value: "Tue", label: "Tuesday" },
  { value: "Wed", label: "Wednesday" },
  { value: "Thu", label: "Thursday" },
  { value: "Fri", label: "Friday" },
  { value: "Sat", label: "Saturday" },
  { value: "Sun", label: "Sunday" },
] as const;

export function AddToRosterDialog({
  open,
  onOpenChange,
  sessionId,
  onAdded,
}: {
  open: boolean;
  onOpenChange: (v: boolean) => void;
  sessionId: string;
  onAdded: () => void;
}) {
  const [form, setForm] = useState<Omit<CreateEnrollmentRequest, "session_id">>({
    student_id: "",
    parent_id: "",
    full_name: "",
  });
  const [error, setError] = useState<string | null>(null);
  const studentsQuery = useQuery({
    queryKey: queryKeys.admin.students(),
    queryFn: listAdminStudents,
    enabled: open,
  });
  const students = studentsQuery.data?.students ?? [];
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
          First month: {formatCents(quoteQuery.data.amount_due_cents)} · billed for{" "}
          {quoteQuery.data.billable_remaining_classes_this_month} of{" "}
          {quoteQuery.data.total_eligible_classes_this_month} classes this month.
          {quoteQuery.data.quote_expires_at
            ? ` Quote expires ${formatShortDateTime(quoteQuery.data.quote_expires_at)}.`
            : ""}
        </p>
      )}
      <form onSubmit={handleSubmit} className="space-y-3">
        {students.length > 0 ? (
          <Field label="Student" required>
            <StudentSelect
              students={students}
              value={form.student_id}
              onChange={(student) =>
                setForm({
                  student_id: student.student_id,
                  parent_id: student.parent_id,
                  full_name: student.full_name,
                })
              }
            />
          </Field>
        ) : (
          <>
            <Field label="Full name" required>
              <input
                type="text"
                required
                value={form.full_name}
                onChange={(e) => setForm((f) => ({ ...f, full_name: e.target.value }))}
                className={inputClass}
              />
            </Field>
            <Field label="Student reference" required>
              <input
                type="text"
                required
                value={form.student_id}
                onChange={(e) => setForm((f) => ({ ...f, student_id: e.target.value }))}
                className={inputClass}
                placeholder={studentsQuery.isLoading ? "Loading students…" : "Student reference"}
              />
            </Field>
            <Field label="Parent reference" required>
              <input
                type="text"
                required
                value={form.parent_id}
                onChange={(e) => setForm((f) => ({ ...f, parent_id: e.target.value }))}
                className={inputClass}
                placeholder="Parent reference"
              />
            </Field>
          </>
        )}
        <DialogActions>
          <Button variant="secondary" size="sm" type="button" onClick={() => onOpenChange(false)}>
            Cancel
          </Button>
          <Button variant="primary" size="sm" type="submit" disabled={mutation.isPending}>
            {mutation.isPending ? "Enrolling…" : "Enroll"}
          </Button>
        </DialogActions>
      </form>
    </RallyDialog>
  );
}

export function PauseEnrollmentDialog({
  enrollment,
  onClose,
  onPaused,
}: {
  enrollment: AdminEnrollmentView | null;
  onClose: () => void;
  onPaused: () => void;
}) {
  const [effectiveDate, setEffectiveDate] = useState(todayDateInput());
  const [billingAction, setBillingAction] = useState<"resume" | "review">("review");
  const [resumeOn, setResumeOn] = useState(dateInputValueFromOffset(30));
  const [reviewOn, setReviewOn] = useState(dateInputValueFromOffset(14));
  const [reason, setReason] = useState("");
  const [error, setError] = useState<string | null>(null);
  const mutation = useMutation({
    mutationFn: () =>
      pauseEnrollment(enrollment!.enrollment_id, {
        effective_date: effectiveDate,
        resume_on: billingAction === "resume" ? resumeOn : null,
        review_on: billingAction === "review" ? reviewOn : null,
        reason: reason || undefined,
      }),
    onSuccess: () => {
      setEffectiveDate(todayDateInput());
      setBillingAction("review");
      setResumeOn(dateInputValueFromOffset(30));
      setReviewOn(dateInputValueFromOffset(14));
      setReason("");
      setError(null);
      onPaused();
    },
    onError: (err: Error) => setError(err.message ?? "Could not pause enrollment."),
  });

  return (
    <RallyDialog
      open={enrollment !== null}
      onOpenChange={(open) => !open && onClose()}
      title="Pause enrollment"
      description={
        enrollment
          ? `Pause ${enrollment.full_name}, release the seat, and move them to the waitlist.`
          : ""
      }
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
        <Field label="Billing follow-up" required>
          <div className="grid gap-2 sm:grid-cols-2">
            <label className="flex items-center gap-2 rounded border border-neutral-200 px-3 py-2 text-sm dark:border-neutral-800">
              <input
                type="radio"
                name="pause-billing-action"
                checked={billingAction === "review"}
                onChange={() => setBillingAction("review")}
              />
              Review before billing resumes
            </label>
            <label className="flex items-center gap-2 rounded border border-neutral-200 px-3 py-2 text-sm dark:border-neutral-800">
              <input
                type="radio"
                name="pause-billing-action"
                checked={billingAction === "resume"}
                onChange={() => setBillingAction("resume")}
              />
              Resume automatically
            </label>
          </div>
        </Field>
        {billingAction === "review" ? (
          <Field label="Review date" required>
            <input
              type="date"
              required
              value={reviewOn}
              onChange={(event) => setReviewOn(event.target.value)}
              className={inputClass}
            />
          </Field>
        ) : (
          <Field label="Resume date" required>
            <input
              type="date"
              required
              value={resumeOn}
              onChange={(event) => setResumeOn(event.target.value)}
              className={inputClass}
            />
          </Field>
        )}
        <p className="text-xs text-rally-subtle">
          Pausing releases the seat and creates a billing deferral that stays visible until the
          review or resume rule is handled.
        </p>
        <Field label="Reason">
          <textarea
            value={reason}
            onChange={(event) => setReason(event.target.value)}
            rows={3}
            className={inputClass}
          />
        </Field>
        <DialogActions>
          <Button variant="secondary" size="sm" type="button" onClick={onClose}>
            Cancel
          </Button>
          <Button
            variant="primary"
            size="sm"
            type="submit"
            disabled={
              !effectiveDate ||
              (billingAction === "review" ? !reviewOn : !resumeOn) ||
              mutation.isPending
            }
          >
            {mutation.isPending ? "Pausing..." : "Pause"}
          </Button>
        </DialogActions>
      </form>
    </RallyDialog>
  );
}

export function TransferEnrollmentDialog({
  enrollment,
  currentSessionId,
  currentSessionTitle,
  onClose,
  onMoved,
}: {
  enrollment: AdminEnrollmentView | null;
  currentSessionId: string;
  currentSessionTitle: string;
  onClose: () => void;
  onMoved: () => void;
}) {
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
    enabled: enrollment !== null,
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
    mutationFn: () =>
      transferEnrollment(enrollment!.enrollment_id, {
        target_session_id: targetSessionId,
        effective_date: effectiveDate,
        reason: reason || undefined,
      }),
    onSuccess: () => {
      setTargetSessionId("");
      setEffectiveDate(todayDateInput());
      setReason("");
      setError(null);
      onMoved();
    },
    onError: (err: Error) => setError(err.message ?? "Failed to move enrollment."),
  });

  return (
    <RallyDialog
      open={enrollment !== null}
      onOpenChange={(open) => !open && onClose()}
      title="Move enrollment"
      description={enrollment ? `Move ${enrollment.full_name} to another session.` : ""}
      overline="Transfer"
    >
      {error && <DialogError message={error} />}
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
        <DialogActions>
          <Button variant="secondary" size="sm" type="button" onClick={onClose}>
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
            {mutation.isPending ? "Moving…" : "Move"}
          </Button>
        </DialogActions>
      </form>
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
  const [withdrawalDate, setWithdrawalDate] = useState(todayDateInput);
  const [outcome, setOutcome] = useState<"credit" | "refund" | "adjustment">("credit");
  const [adminNote, setAdminNote] = useState("");
  const [error, setError] = useState<string | null>(null);
  const previewMutation = useMutation({
    mutationFn: () =>
      previewWithdrawalCredit(enrollment!.enrollment_id, {
        withdrawal_date: `${withdrawalDate}T00:00:00.000Z`,
      }),
    onError: (err: Error) => setError(err.message ?? "Could not preview credit."),
  });
  const approveMutation = useMutation({
    mutationFn: async () => {
      if (outcome === "credit") {
        await approveWithdrawalCredit(enrollment!.enrollment_id, {
          withdrawal_date: `${withdrawalDate}T00:00:00.000Z`,
          admin_note: adminNote,
        });
        return;
      }
      await withdrawEnrollment(enrollment!.enrollment_id, {
        effective_date: withdrawalDate,
        outcome,
        reason: adminNote || `Withdrawal ${outcome}`,
      });
    },
    onSuccess: () => {
      setOutcome("credit");
      setAdminNote("");
      setError(null);
      onApproved();
    },
    onError: (err: Error) => setError(err.message ?? "Could not approve credit."),
  });
  const preview = previewMutation.data;
  return (
    <Dialog.Root open={enrollment !== null} onOpenChange={(open) => !open && onClose()}>
      <Dialog.Portal>
        <Dialog.Overlay className="fixed inset-0 z-50 bg-black/40" />
        <Dialog.Content
          className="fixed left-1/2 top-1/2 z-50 w-full max-w-md -translate-x-1/2 -translate-y-1/2 rounded-xl bg-white p-6 shadow-xl focus:outline-none dark:bg-neutral-900"
          aria-describedby="withdrawal-credit-desc"
        >
          <Dialog.Title className="mb-1 text-lg font-semibold">Withdraw enrollment</Dialog.Title>
          <Dialog.Description id="withdrawal-credit-desc" className="mb-4 text-sm text-neutral-500">
            {enrollment ? `Preview unused-class credit for ${enrollment.full_name}.` : ""}
          </Dialog.Description>
          {error && (
            <p role="alert" className="mb-3 rounded-md bg-red-50 p-2 text-sm text-red-700 dark:bg-red-950 dark:text-red-300">
              {error}
            </p>
          )}
          <div className="space-y-3">
            <Field label="Outcome" required>
              <select
                value={outcome}
                onChange={(event) => {
                  setOutcome(event.target.value as "credit" | "refund" | "adjustment");
                  previewMutation.reset();
                }}
                className={inputClass}
              >
                <option value="credit">Account credit</option>
                <option value="refund">Refund</option>
                <option value="adjustment">Admin adjustment</option>
              </select>
            </Field>
            <Field label="Withdrawal date" required>
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
            <Field label="Admin note">
              <textarea
                value={adminNote}
                onChange={(event) => setAdminNote(event.target.value)}
                rows={3}
                className={inputClass}
              />
            </Field>
            <div className="flex justify-end gap-2 pt-2">
              <button
                type="button"
                onClick={onClose}
                className="min-h-touch rounded-md border border-neutral-300 px-4 text-sm dark:border-neutral-700"
              >
                Cancel
              </button>
              <button
                type="button"
                disabled={
                  !withdrawalDate ||
                  approveMutation.isPending ||
                  (outcome === "credit" && !preview)
                }
                onClick={() => approveMutation.mutate()}
                className="min-h-touch rounded-md bg-orange-600 px-4 text-sm font-medium text-white hover:bg-orange-700 disabled:opacity-60"
              >
                {approveMutation.isPending ? "Saving..." : "Withdraw"}
              </button>
            </div>
          </div>
        </Dialog.Content>
      </Dialog.Portal>
    </Dialog.Root>
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
      title="Remove enrollment"
      description={enrollment ? `Remove ${enrollment.full_name} from this roster.` : ""}
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
            {mutation.isPending ? "Removing..." : "Remove"}
          </Button>
        </DialogActions>
      </form>
    </RallyDialog>
  );
}

export function StudentSelect({
  students,
  value,
  onChange,
}: {
  students: AdminStudentView[];
  value: string;
  onChange: (student: AdminStudentView) => void;
}) {
  return (
    <select
      required
      value={value}
      onChange={(e) => {
        const selected = students.find((s) => s.student_id === e.target.value);
        if (selected) onChange(selected);
      }}
      className={inputClass}
    >
      <option value="">Select student</option>
      {students.map((student) => (
        <option key={student.student_id} value={student.student_id}>
          {student.full_name}
        </option>
      ))}
    </select>
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

export function DaySelect({
  value,
  onChange,
}: {
  value: string;
  onChange: (day: string) => void;
}) {
  return (
    <select required value={value} onChange={(event) => onChange(event.target.value)} className={inputClass}>
      {DAYS_OF_WEEK.map((day) => (
        <option key={day.value} value={day.value}>
          {day.label}
        </option>
      ))}
    </select>
  );
}
