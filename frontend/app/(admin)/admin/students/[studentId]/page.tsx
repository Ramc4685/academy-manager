"use client";

/**
 * Admin student detail page.
 *
 * Pulls a single student from the v2 BFF and exposes safe admin-editable
 * fields. No raw internal ids are rendered in normal UI.
 */

import { useEffect, useMemo, useState } from "react";
import Link from "next/link";
import { useParams } from "next/navigation";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { ArrowLeft, RefreshCw } from "lucide-react";

import {
  changeAdminStudentParent,
  listAdminSessions,
  listAdminUsers,
  type AdminSessionView,
  type AdminUserView,
  type ChangeAdminStudentParentRequest,
} from "@/lib/api/admin";
import {
  getAdminStudent,
  transferEnrollment,
  updateAdminStudent,
  type AdminStudentDetail,
  type AdminStudentPaymentSummary,
  type AdminStudentSessionSummary,
  type UpdateAdminStudentRequest,
} from "@/lib/api/v2/students";
import { queryKeys } from "@/lib/query/keys";
import { Avatar } from "@/components/ds/avatar";
import { Button } from "@/components/ds/button";
import { Card } from "@/components/ds/card";
import { Chip } from "@/components/ds/chip";
import { Overline } from "@/components/ds/typography";

type EditableStatus = "active" | "paused" | "inactive";

export default function AdminStudentDetailPage() {
  const params = useParams<{ studentId: string }>();
  const studentId = params?.studentId ?? "";
  const queryClient = useQueryClient();

  const studentQuery = useQuery({
    queryKey: queryKeys.admin.studentDetail(studentId),
    queryFn: () => getAdminStudent(studentId),
    enabled: Boolean(studentId),
    retry: false,
  });
  const parentsQuery = useQuery({
    queryKey: queryKeys.admin.users("parent"),
    queryFn: () => listAdminUsers("parent"),
    enabled: Boolean(studentId),
  });

  if (!studentId) {
    return (
      <section className="space-y-4">
        <BackLink />
        <Card p={20}>
          <p className="text-sm text-rally-muted">Missing student id.</p>
        </Card>
      </section>
    );
  }

  if (studentQuery.isPending) {
    return (
      <section className="space-y-4">
        <BackLink />
        <Card p={20}>
          <div
            className="h-24 animate-pulse rounded-lg bg-neutral-100 dark:bg-neutral-800"
            aria-label="Loading student"
          />
        </Card>
      </section>
    );
  }

  if (studentQuery.isError) {
    return (
      <section className="space-y-4">
        <BackLink />
        <Card p={20}>
          <p role="alert" className="text-sm text-red-700">
            Could not load student.
          </p>
        </Card>
      </section>
    );
  }

  const student = studentQuery.data;
  if (!student) {
    return (
      <section className="space-y-4">
        <BackLink />
        <Card p={20}>
          <p className="text-sm text-rally-muted">Student not found.</p>
        </Card>
      </section>
    );
  }

  return (
    <section
      className="space-y-6"
      data-testid="admin-student-detail"
      data-student-id={student.student_id}
    >
      <BackLink />
      <Header student={student} />
      <div className="grid gap-6 lg:grid-cols-3">
        <Card p={20} className="lg:col-span-2">
          <Overline>Profile</Overline>
          <StudentEditForm
            student={student}
            onSaved={() => {
              void queryClient.invalidateQueries({
                queryKey: queryKeys.admin.studentDetail(studentId),
              });
              void queryClient.invalidateQueries({
                queryKey: ["admin", "students"],
              });
            }}
          />
        </Card>
        <CurrentPaymentPanel student={student} />
        <SessionsPanel
          sessions={student.enrolled_sessions ?? []}
          studentId={studentId}
          queryClient={queryClient}
        />
        <Card p={20}>
          <Overline>Engagement</Overline>
          <DetailList
            rows={[
              {
                label: "Active sessions",
                value: String(student.active_session_count),
              },
              {
                label: "Attendance (30d)",
                value:
                  student.attendance_rate == null
                    ? "—"
                    : `${Math.round(Math.max(0, Math.min(student.attendance_rate, 1)) * 100)}%`,
              },
              {
                label: "Last attended",
                value: student.last_seen_at
                  ? new Date(student.last_seen_at).toLocaleDateString()
                  : "—",
              },
              {
                label: "Dues",
                value: student.dues_status.toUpperCase(),
              },
            ]}
          />
        </Card>
        <PaymentHistoryPanel payments={student.payment_history ?? []} />
        <Card p={20}>
          <Overline>Parent account</Overline>
          <ChangeParentPanel
            student={student}
            parents={parentsQuery.data?.users ?? []}
            parentsLoading={parentsQuery.isLoading}
            parentsError={parentsQuery.isError}
            onSaved={() => {
              void queryClient.invalidateQueries({
                queryKey: queryKeys.admin.studentDetail(studentId),
              });
              void queryClient.invalidateQueries({
                queryKey: ["admin", "students"],
              });
              void queryClient.invalidateQueries({
                queryKey: queryKeys.admin.users("parent"),
              });
            }}
          />
        </Card>
      </div>
    </section>
  );
}

function CurrentPaymentPanel({ student }: { student: AdminStudentDetail }) {
  const current = student.current_payment;
  return (
    <Card p={20}>
      <Overline>Current payment</Overline>
      {current ? (
        <div
          className="mt-3 space-y-3"
          data-testid="admin-student-current-payment"
        >
          <div>
            <div className="font-mono text-2xl font-semibold tabular-nums text-rally-ink">
              {formatCurrencyCents(current.amount_cents)}
            </div>
            <div className="mt-1 flex flex-wrap items-center gap-2 text-xs text-rally-muted">
              <StatusChip status={current.status} />
              <span>
                {current.source === "invoice"
                  ? "Invoice balance"
                  : "Session price"}
              </span>
            </div>
          </div>
          <DetailList
            rows={[
              { label: "Period", value: current.period ?? "—" },
              { label: "Payment", value: current.payment_id ?? "—" },
              { label: "Session", value: current.session_id ?? "—" },
            ]}
          />
        </div>
      ) : (
        <p
          className="mt-3 text-sm text-rally-muted"
          data-testid="admin-student-no-current-payment"
        >
          No current balance.
        </p>
      )}
    </Card>
  );
}

function SessionsPanel({
  sessions,
  studentId,
  queryClient,
}: {
  sessions: AdminStudentSessionSummary[];
  studentId: string;
  queryClient: ReturnType<typeof useQueryClient>;
}) {
  const [moving, setMoving] = useState<AdminStudentSessionSummary | null>(null);
  const [targetSessionId, setTargetSessionId] = useState("");
  const [effectiveDate, setEffectiveDate] = useState(() =>
    new Date().toISOString().slice(0, 10),
  );
  const [reason, setReason] = useState("");

  const sessionsQuery = useQuery({
    queryKey: queryKeys.admin.sessions("upcoming"),
    queryFn: () => listAdminSessions(undefined, { window: "upcoming" }),
    enabled: Boolean(moving),
  });

  const transferMutation = useMutation({
    mutationFn: () =>
      transferEnrollment(moving!.enrollment_id, {
        target_session_id: targetSessionId,
        effective_date: effectiveDate,
        reason: reason || null,
      }),
    onSuccess: () => {
      void queryClient.invalidateQueries({
        queryKey: queryKeys.admin.studentDetail(studentId),
      });
      setMoving(null);
      setTargetSessionId("");
      setReason("");
    },
  });

  const availableSessions: AdminSessionView[] = (
    sessionsQuery.data?.sessions ?? []
  ).filter((s) => s.session_id !== moving?.session_id);

  useEffect(() => {
    if (!moving) return;
    const onKeyDown = (event: KeyboardEvent) => {
      if (event.key === "Escape" && !transferMutation.isPending) {
        setMoving(null);
      }
    };
    window.addEventListener("keydown", onKeyDown);
    return () => window.removeEventListener("keydown", onKeyDown);
  }, [moving, transferMutation.isPending]);

  return (
    <>
      <Card p={20} className="lg:col-span-2">
        <div className="flex items-center justify-between gap-3">
          <Overline>Enrolled sessions</Overline>
          <span className="font-mono text-xs text-rally-muted tabular-nums">
            {sessions.length} active
          </span>
        </div>
        {sessions.length === 0 ? (
          <p
            className="mt-3 text-sm text-rally-muted"
            data-testid="admin-student-no-sessions"
          >
            No active session enrollments.
          </p>
        ) : (
          <div
            className="mt-3 overflow-x-auto"
            data-testid="admin-student-enrolled-sessions"
          >
            <table className="min-w-full text-left text-sm">
              <thead className="border-b border-neutral-200 text-xs uppercase tracking-overline text-rally-muted">
                <tr>
                  <th className="py-2 pr-4 font-medium">Session</th>
                  <th className="py-2 pr-4 font-medium">Schedule</th>
                  <th className="py-2 pr-4 font-medium">Billing</th>
                  <th className="py-2 pr-4 font-medium">Status</th>
                  <th className="py-2 font-medium" />
                </tr>
              </thead>
              <tbody className="divide-y divide-neutral-100">
                {sessions.map((session) => (
                  <tr key={session.enrollment_id}>
                    <td className="py-3 pr-4 align-top">
                      <div className="font-medium text-rally-ink">
                        {session.session_title}
                      </div>
                      <div className="text-xs text-rally-muted">
                        {session.location ?? session.session_id}
                      </div>
                    </td>
                    <td className="py-3 pr-4 align-top text-rally-muted">
                      {formatDateTimeRange(session.start_at, session.end_at)}
                    </td>
                    <td className="py-3 pr-4 align-top">
                      <div className="font-mono tabular-nums text-rally-ink">
                        {session.amount_cents == null
                          ? "—"
                          : formatCurrencyCents(session.amount_cents)}
                      </div>
                      <div className="text-xs text-rally-muted">
                        {session.payment_mode ??
                          session.subscription_status ??
                          "—"}
                      </div>
                    </td>
                    <td className="py-3 pr-4 align-top">
                      <StatusChip
                        status={session.subscription_status ?? session.status}
                      />
                    </td>
                    <td className="py-3 align-top">
                      <button
                        className="text-xs font-medium text-rally-blue hover:underline"
                        onClick={() => {
                          setMoving(session);
                          setTargetSessionId("");
                          setReason("");
                          setEffectiveDate(
                            new Date().toISOString().slice(0, 10),
                          );
                        }}
                      >
                        Move
                      </button>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </Card>

      {moving && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/40 p-4">
          <div
            role="dialog"
            aria-modal="true"
            aria-labelledby="move-session-title"
            className="w-full max-w-md rounded-xl bg-white p-6 shadow-xl dark:bg-neutral-900"
          >
            <h2
              id="move-session-title"
              className="mb-1 text-base font-semibold text-rally-ink"
            >
              Move student session
            </h2>
            <p className="mb-4 text-sm text-rally-muted">
              Moving <span className="font-medium">{moving.session_title}</span>
            </p>

            {transferMutation.isError && (
              <p className="mb-3 rounded bg-red-50 px-3 py-2 text-xs text-red-600">
                {String(transferMutation.error)}
              </p>
            )}

            <div className="space-y-3">
              <div>
                <label className="mb-1 block text-xs font-medium uppercase tracking-overline text-rally-muted">
                  New session
                </label>
                <select
                  className="w-full rounded-lg border border-neutral-200 bg-white px-3 py-2 text-sm text-rally-ink focus:outline-none focus:ring-2 focus:ring-rally-blue dark:bg-neutral-800"
                  value={targetSessionId}
                  onChange={(e) => setTargetSessionId(e.target.value)}
                  disabled={sessionsQuery.isPending}
                >
                  <option value="">
                    {sessionsQuery.isPending ? "Loading…" : "Select a session"}
                  </option>
                  {availableSessions.map((s) => (
                    <option key={s.session_id} value={s.session_id}>
                      {s.title} {s.coach_name ? `— ${s.coach_name}` : ""}
                    </option>
                  ))}
                </select>
              </div>

              <div>
                <label className="mb-1 block text-xs font-medium uppercase tracking-overline text-rally-muted">
                  Effective date
                </label>
                <input
                  type="date"
                  className="w-full rounded-lg border border-neutral-200 bg-white px-3 py-2 text-sm text-rally-ink focus:outline-none focus:ring-2 focus:ring-rally-blue dark:bg-neutral-800"
                  value={effectiveDate}
                  onChange={(e) => setEffectiveDate(e.target.value)}
                />
              </div>

              <div>
                <label className="mb-1 block text-xs font-medium uppercase tracking-overline text-rally-muted">
                  Reason (optional)
                </label>
                <textarea
                  className="w-full rounded-lg border border-neutral-200 bg-white px-3 py-2 text-sm text-rally-ink focus:outline-none focus:ring-2 focus:ring-rally-blue dark:bg-neutral-800"
                  rows={2}
                  placeholder="e.g. schedule conflict"
                  value={reason}
                  onChange={(e) => setReason(e.target.value)}
                />
              </div>
            </div>

            <div className="mt-5 flex justify-end gap-2">
              <Button
                variant="ghost"
                size="sm"
                onClick={() => setMoving(null)}
                disabled={transferMutation.isPending}
              >
                Cancel
              </Button>
              <Button
                size="sm"
                onClick={() => transferMutation.mutate()}
                disabled={!targetSessionId || transferMutation.isPending}
              >
                {transferMutation.isPending ? "Moving…" : "Move student"}
              </Button>
            </div>
          </div>
        </div>
      )}
    </>
  );
}

function PaymentHistoryPanel({
  payments,
}: {
  payments: AdminStudentPaymentSummary[];
}) {
  return (
    <Card p={20} className="lg:col-span-2">
      <div className="flex items-center justify-between gap-3">
        <Overline>Payment history</Overline>
        <span className="font-mono text-xs text-rally-muted tabular-nums">
          {payments.length} records
        </span>
      </div>
      {payments.length === 0 ? (
        <p
          className="mt-3 text-sm text-rally-muted"
          data-testid="admin-student-no-payments"
        >
          No payment records.
        </p>
      ) : (
        <div
          className="mt-3 overflow-x-auto"
          data-testid="admin-student-payment-history"
        >
          <table className="min-w-full text-left text-sm">
            <thead className="border-b border-neutral-200 text-xs uppercase tracking-overline text-rally-muted">
              <tr>
                <th className="py-2 pr-4 font-medium">Date</th>
                <th className="py-2 pr-4 font-medium">Period</th>
                <th className="py-2 pr-4 font-medium">Amount</th>
                <th className="py-2 pr-4 font-medium">Paid</th>
                <th className="py-2 pr-4 font-medium">Balance</th>
                <th className="py-2 font-medium">Status</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-neutral-100">
              {payments.map((payment) => (
                <tr key={payment.payment_id}>
                  <td className="py-3 pr-4 align-top text-rally-muted">
                    {formatDate(payment.created_at)}
                  </td>
                  <td className="py-3 pr-4 align-top text-rally-ink">
                    {payment.period ?? "—"}
                  </td>
                  <td className="py-3 pr-4 align-top font-mono tabular-nums text-rally-ink">
                    {formatCurrencyCents(payment.amount_cents)}
                  </td>
                  <td className="py-3 pr-4 align-top font-mono tabular-nums text-rally-ink">
                    {formatCurrencyCents(payment.paid_amount_cents)}
                  </td>
                  <td className="py-3 pr-4 align-top font-mono tabular-nums text-rally-ink">
                    {formatCurrencyCents(payment.balance_due_cents)}
                  </td>
                  <td className="py-3 align-top">
                    <StatusChip status={payment.status} />
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </Card>
  );
}

function BackLink() {
  return (
    <Link
      href="/admin/students"
      className="inline-flex items-center gap-1.5 text-sm text-rally-muted hover:text-rally-ink focus:outline-none focus:ring-2 focus:ring-rally-cobalt-600 rounded"
    >
      <ArrowLeft className="size-4" aria-hidden="true" />
      <span>All students</span>
    </Link>
  );
}

function Header({ student }: { student: AdminStudentDetail }) {
  return (
    <Card p={20}>
      <div className="flex flex-col gap-4 sm:flex-row sm:items-center sm:justify-between">
        <div className="flex items-center gap-4 min-w-0">
          <Avatar name={student.full_name} size={56} />
          <div className="min-w-0">
            <h2 className="font-display text-xl font-semibold tracking-[-0.01em] text-rally-ink truncate">
              {student.full_name}
            </h2>
            <div className="mt-1 flex items-center gap-2">
              <StatusChip status={student.status} />
            </div>
          </div>
        </div>
        <div className="text-sm text-rally-muted">
          <div className="font-medium text-rally-ink">
            {student.parent_name ?? student.parent_email ?? "Parent on file"}
          </div>
          {student.parent_email && (
            <a
              href={`mailto:${student.parent_email}`}
              className="block hover:underline focus:outline-none focus:ring-2 focus:ring-rally-cobalt-600 rounded"
            >
              {student.parent_email}
            </a>
          )}
          {student.parent_phone && (
            <a
              href={`tel:${student.parent_phone}`}
              className="block hover:underline focus:outline-none focus:ring-2 focus:ring-rally-cobalt-600 rounded"
            >
              {student.parent_phone}
            </a>
          )}
        </div>
      </div>
    </Card>
  );
}

function StatusChip({ status }: { status: string }) {
  const normalized = status.toLowerCase();
  const variant =
    normalized === "active" || normalized === "succeeded"
      ? "enrolled"
      : normalized === "paid"
        ? "paid"
        : normalized === "paused"
          ? "paused"
          : normalized === "pending" ||
              normalized === "unpaid" ||
              normalized === "open"
            ? "pending"
            : normalized === "failed"
              ? "failed"
              : normalized === "partially_paid" || normalized === "partial"
                ? "partial"
                : "expired";
  return <Chip variant={variant} label={status.toUpperCase()} />;
}

function formatCurrencyCents(cents: number) {
  return new Intl.NumberFormat("en-US", {
    style: "currency",
    currency: "USD",
    maximumFractionDigits: 0,
  }).format(cents / 100);
}

function formatDate(value: string | null | undefined) {
  if (!value) return "—";
  return new Date(value).toLocaleDateString();
}

function formatDateTime(value: string | null | undefined) {
  if (!value) return "—";
  return new Date(value).toLocaleString([], {
    month: "short",
    day: "numeric",
    hour: "numeric",
    minute: "2-digit",
  });
}

function formatDateTimeRange(
  startAt: string | null | undefined,
  endAt: string | null | undefined,
) {
  if (!startAt && !endAt) return "—";
  if (!endAt) return formatDateTime(startAt);
  if (!startAt) return formatDateTime(endAt);
  return `${formatDateTime(startAt)} - ${formatDateTime(endAt)}`;
}

function DetailList({
  rows,
}: {
  rows: Array<{ label: string; value: string }>;
}) {
  return (
    <dl className="mt-3 grid grid-cols-1 gap-3 text-sm">
      {rows.map((row) => (
        <div key={row.label} className="flex items-center justify-between">
          <dt className="text-rally-muted">{row.label}</dt>
          <dd className="font-mono text-rally-ink tabular-nums">{row.value}</dd>
        </div>
      ))}
    </dl>
  );
}

function StudentEditForm({
  student,
  onSaved,
}: {
  student: AdminStudentDetail;
  onSaved: () => void;
}) {
  const [fullName, setFullName] = useState(student.full_name);
  const [dateOfBirth, setDateOfBirth] = useState(student.date_of_birth ?? "");
  const [level, setLevel] = useState(student.level ?? "");
  const [status, setStatus] = useState<EditableStatus>(
    (student.status as EditableStatus) ?? "active",
  );
  const [notes, setNotes] = useState(student.notes ?? "");
  const [reason, setReason] = useState("Admin profile update");
  const [submitError, setSubmitError] = useState<string | null>(null);
  const [submitOk, setSubmitOk] = useState(false);

  // Keep local state in sync if the server-side data refreshes.
  useEffect(() => {
    setFullName(student.full_name);
    setDateOfBirth(student.date_of_birth ?? "");
    setLevel(student.level ?? "");
    setStatus((student.status as EditableStatus) ?? "active");
    setNotes(student.notes ?? "");
  }, [
    student.full_name,
    student.date_of_birth,
    student.level,
    student.status,
    student.notes,
  ]);

  const mutation = useMutation({
    mutationFn: (payload: UpdateAdminStudentRequest) =>
      updateAdminStudent(student.student_id, payload),
    onSuccess: () => {
      setSubmitError(null);
      setSubmitOk(true);
      onSaved();
    },
    onError: (err: unknown) => {
      setSubmitOk(false);
      const message =
        err instanceof Error ? err.message : "Could not save changes.";
      setSubmitError(message);
    },
  });

  const dirty =
    fullName !== student.full_name ||
    dateOfBirth !== (student.date_of_birth ?? "") ||
    level !== (student.level ?? "") ||
    status !== student.status ||
    (notes ?? "") !== (student.notes ?? "");

  return (
    <form
      className="mt-3 space-y-4"
      data-testid="admin-student-edit-form"
      onSubmit={(e) => {
        e.preventDefault();
        setSubmitOk(false);
        setSubmitError(null);
        const payload: UpdateAdminStudentRequest = {};
        if (fullName !== student.full_name) payload.full_name = fullName;
        if (dateOfBirth !== (student.date_of_birth ?? ""))
          payload.date_of_birth = dateOfBirth || null;
        if (level !== (student.level ?? "")) payload.level = level || null;
        if (status !== student.status) payload.status = status;
        if ((notes ?? "") !== (student.notes ?? ""))
          payload.notes = notes || null;
        payload.reason = reason;
        mutation.mutate(payload);
      }}
    >
      <Field label="Full name" htmlFor="student-full-name">
        <input
          id="student-full-name"
          value={fullName}
          onChange={(e) => setFullName(e.target.value)}
          className="h-10 w-full rounded-md border border-neutral-200 bg-white px-3 text-sm text-rally-base outline-none focus:border-rally-cobalt-600 focus:ring-2 focus:ring-rally-cobalt-600/15"
          required
          minLength={1}
          maxLength={120}
        />
      </Field>

      <div className="grid gap-4 sm:grid-cols-2">
        <Field label="Date of birth" htmlFor="student-dob">
          <input
            id="student-dob"
            type="date"
            value={dateOfBirth}
            onChange={(e) => setDateOfBirth(e.target.value)}
            className="h-10 w-full rounded-md border border-neutral-200 bg-white px-3 text-sm text-rally-base outline-none focus:border-rally-cobalt-600 focus:ring-2 focus:ring-rally-cobalt-600/15"
          />
        </Field>

        <Field label="Level" htmlFor="student-level">
          <input
            id="student-level"
            value={level}
            onChange={(e) => setLevel(e.target.value)}
            className="h-10 w-full rounded-md border border-neutral-200 bg-white px-3 text-sm text-rally-base outline-none focus:border-rally-cobalt-600 focus:ring-2 focus:ring-rally-cobalt-600/15"
            maxLength={80}
          />
        </Field>
      </div>

      <Field label="Status" htmlFor="student-status">
        <select
          id="student-status"
          value={status}
          onChange={(e) => setStatus(e.target.value as EditableStatus)}
          className="h-10 w-full rounded-md border border-neutral-200 bg-white px-3 text-sm text-rally-base outline-none focus:border-rally-cobalt-600 focus:ring-2 focus:ring-rally-cobalt-600/15"
        >
          <option value="active">Active</option>
          <option value="paused">Paused</option>
          <option value="inactive">Inactive</option>
        </select>
      </Field>

      <Field label="Internal notes" htmlFor="student-notes">
        <textarea
          id="student-notes"
          value={notes}
          onChange={(e) => setNotes(e.target.value)}
          rows={4}
          maxLength={2000}
          className="w-full rounded-md border border-neutral-200 bg-white px-3 py-2 text-sm text-rally-base outline-none focus:border-rally-cobalt-600 focus:ring-2 focus:ring-rally-cobalt-600/15"
          placeholder="Allergies, behavioural notes, comms preferences…"
        />
      </Field>

      <Field label="Reason" htmlFor="student-edit-reason">
        <input
          id="student-edit-reason"
          value={reason}
          onChange={(e) => setReason(e.target.value)}
          className="h-10 w-full rounded-md border border-neutral-200 bg-white px-3 text-sm text-rally-base outline-none focus:border-rally-cobalt-600 focus:ring-2 focus:ring-rally-cobalt-600/15"
          required
          maxLength={500}
        />
      </Field>

      {submitError && (
        <p
          role="alert"
          data-testid="admin-student-edit-error"
          className="rounded-md border border-red-200 bg-red-50 p-2 text-sm text-red-700"
        >
          {submitError}
        </p>
      )}
      {submitOk && (
        <p
          role="status"
          data-testid="admin-student-edit-ok"
          className="rounded-md border border-emerald-200 bg-emerald-50 p-2 text-sm text-emerald-800"
        >
          Saved.
        </p>
      )}

      <div className="flex items-center gap-2">
        <Button
          type="submit"
          variant="primary"
          size="sm"
          disabled={!dirty || mutation.isPending}
          icon={
            mutation.isPending ? (
              <RefreshCw className="size-3.5 animate-spin" />
            ) : undefined
          }
        >
          {mutation.isPending ? "Saving…" : "Save changes"}
        </Button>
        {dirty && (
          <Button
            type="button"
            variant="secondary"
            size="sm"
            onClick={() => {
              setFullName(student.full_name);
              setDateOfBirth(student.date_of_birth ?? "");
              setLevel(student.level ?? "");
              setStatus((student.status as EditableStatus) ?? "active");
              setNotes(student.notes ?? "");
              setSubmitError(null);
              setSubmitOk(false);
            }}
          >
            Reset
          </Button>
        )}
      </div>
    </form>
  );
}

function ChangeParentPanel({
  student,
  parents,
  parentsLoading,
  parentsError,
  onSaved,
}: {
  student: AdminStudentDetail;
  parents: AdminUserView[];
  parentsLoading: boolean;
  parentsError: boolean;
  onSaved: () => void;
}) {
  const activeParents = useMemo(
    () => parents.filter((parent) => parent.status === "active"),
    [parents],
  );
  const [search, setSearch] = useState("");
  const [parentId, setParentId] = useState("");
  const [reason, setReason] = useState("Admin parent account correction");
  const [submitError, setSubmitError] = useState<string | null>(null);
  const [submitOk, setSubmitOk] = useState(false);
  const [warnings, setWarnings] = useState<string[]>([]);

  const filteredParents = useMemo(() => {
    const normalized = search.trim().toLowerCase();
    if (!normalized) return activeParents;
    return activeParents.filter((parent) => {
      const haystack =
        `${parent.display_name} ${parent.email} ${parent.phone ?? ""}`.toLowerCase();
      return haystack.includes(normalized);
    });
  }, [activeParents, search]);

  useEffect(() => {
    if (
      !parentId ||
      filteredParents.some((parent) => parent.user_id === parentId)
    )
      return;
    setParentId("");
  }, [filteredParents, parentId]);

  useEffect(() => {
    setParentId("");
    setSubmitError(null);
    setSubmitOk(false);
    setWarnings([]);
  }, [student.student_id, student.parent_id]);

  const selectedParent = activeParents.find(
    (parent) => parent.user_id === parentId,
  );
  const canSubmit = Boolean(
    parentId && parentId !== student.parent_id && reason.trim(),
  );

  const mutation = useMutation({
    mutationFn: (payload: ChangeAdminStudentParentRequest) =>
      changeAdminStudentParent(student.student_id, payload),
    onSuccess: (result) => {
      setSubmitError(null);
      setSubmitOk(true);
      setWarnings(result.warnings);
      setParentId("");
      setSearch("");
      onSaved();
    },
    onError: (err: unknown) => {
      setSubmitOk(false);
      setWarnings([]);
      setSubmitError(
        err instanceof Error ? err.message : "Could not change parent account.",
      );
    },
  });

  return (
    <form
      className="mt-3 space-y-4"
      data-testid="admin-student-change-parent-form"
      onSubmit={(event) => {
        event.preventDefault();
        if (!canSubmit) return;
        setSubmitError(null);
        setSubmitOk(false);
        setWarnings([]);
        mutation.mutate({ parent_id: parentId, reason: reason.trim() });
      }}
    >
      <DetailList
        rows={[
          {
            label: "Current parent",
            value:
              student.parent_name ?? student.parent_email ?? "Parent on file",
          },
          {
            label: "Available parents",
            value: parentsLoading ? "Loading" : String(activeParents.length),
          },
        ]}
      />

      {parentsError && (
        <p
          role="alert"
          className="rounded-md border border-red-200 bg-red-50 p-2 text-sm text-red-700"
        >
          Could not load parent accounts.
        </p>
      )}

      <Field label="Search parents" htmlFor="student-parent-search">
        <input
          id="student-parent-search"
          value={search}
          onChange={(event) => setSearch(event.target.value)}
          className="h-10 w-full rounded-md border border-neutral-200 bg-white px-3 text-sm text-rally-base outline-none focus:border-rally-cobalt-600 focus:ring-2 focus:ring-rally-cobalt-600/15"
          placeholder="Name, email, or phone"
          disabled={parentsLoading || parentsError}
        />
      </Field>

      <Field label="New parent" htmlFor="student-parent-id">
        <select
          id="student-parent-id"
          value={parentId}
          onChange={(event) => {
            setParentId(event.target.value);
            setSubmitOk(false);
            setSubmitError(null);
          }}
          className="h-10 w-full rounded-md border border-neutral-200 bg-white px-3 text-sm text-rally-base outline-none focus:border-rally-cobalt-600 focus:ring-2 focus:ring-rally-cobalt-600/15"
          disabled={
            parentsLoading || parentsError || filteredParents.length === 0
          }
          required
        >
          <option value="">
            {parentsLoading
              ? "Loading parents..."
              : filteredParents.length === 0
                ? "No active parents found"
                : "Select a parent"}
          </option>
          {filteredParents.map((parent) => (
            <option key={parent.user_id} value={parent.user_id}>
              {parent.display_name} ({parent.email})
            </option>
          ))}
        </select>
      </Field>

      {selectedParent && (
        <div className="rounded-md border border-neutral-200 bg-neutral-50 p-3 text-sm">
          <div className="font-medium text-rally-ink">
            {selectedParent.display_name}
          </div>
          <div className="text-rally-muted">{selectedParent.email}</div>
          {selectedParent.phone && (
            <div className="text-rally-muted">{selectedParent.phone}</div>
          )}
        </div>
      )}

      <Field label="Reason" htmlFor="student-parent-reason">
        <input
          id="student-parent-reason"
          value={reason}
          onChange={(event) => setReason(event.target.value)}
          className="h-10 w-full rounded-md border border-neutral-200 bg-white px-3 text-sm text-rally-base outline-none focus:border-rally-cobalt-600 focus:ring-2 focus:ring-rally-cobalt-600/15"
          required
          maxLength={500}
        />
      </Field>

      {submitError && (
        <p
          role="alert"
          data-testid="admin-student-change-parent-error"
          className="rounded-md border border-red-200 bg-red-50 p-2 text-sm text-red-700"
        >
          {submitError}
        </p>
      )}
      {submitOk && (
        <p
          role="status"
          data-testid="admin-student-change-parent-ok"
          className="rounded-md border border-emerald-200 bg-emerald-50 p-2 text-sm text-emerald-800"
        >
          Parent account changed.
        </p>
      )}
      {warnings.length > 0 && (
        <div className="rounded-md border border-amber-200 bg-amber-50 p-2 text-sm text-amber-900">
          {warnings.map((warning) => (
            <div key={warning}>{warning}</div>
          ))}
        </div>
      )}

      <Button
        type="submit"
        variant="primary"
        size="sm"
        disabled={
          !canSubmit || mutation.isPending || parentsLoading || parentsError
        }
        icon={
          mutation.isPending ? (
            <RefreshCw className="size-3.5 animate-spin" />
          ) : undefined
        }
      >
        {mutation.isPending ? "Changing..." : "Change parent"}
      </Button>
    </form>
  );
}

function Field({
  label,
  htmlFor,
  children,
}: {
  label: string;
  htmlFor: string;
  children: React.ReactNode;
}) {
  return (
    <div className="space-y-1.5">
      <label
        htmlFor={htmlFor}
        className="font-mono text-[10px] font-bold uppercase tracking-overline text-rally-muted"
      >
        {label}
      </label>
      {children}
    </div>
  );
}
