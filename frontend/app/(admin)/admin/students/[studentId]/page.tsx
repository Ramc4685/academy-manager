"use client";

/**
 * Admin student detail page.
 *
 * Wave 5 — Agent B. Pulls a single student from the v2 BFF and exposes
 * an edit form for the fields the backend will support. The PATCH route
 * (`/api/v2/admin/students/{id}`) is not yet shipped (see TODO inside
 * `lib/api/v2/students.ts`), so the form surfaces backend errors rather
 * than silently faking success.
 *
 * No raw internal ids are rendered in normal UI — the `student_id` is
 * tucked behind a copy-on-click affordance per the Wave 5 design rules.
 */

import { useEffect, useState } from "react";
import Link from "next/link";
import { useParams } from "next/navigation";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { ArrowLeft, Copy, RefreshCw } from "lucide-react";

import {
  getAdminStudent,
  updateAdminStudent,
  type AdminStudentDetail,
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
              void queryClient.invalidateQueries({ queryKey: ["admin", "students"] });
            }}
          />
        </Card>
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
      </div>
    </section>
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
              <CopyIdButton id={student.student_id} label="Student ref" />
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
              className="font-mono text-[12px] hover:underline focus:outline-none focus:ring-2 focus:ring-rally-cobalt-600 rounded"
            >
              {student.parent_email}
            </a>
          )}
        </div>
      </div>
    </Card>
  );
}

function StatusChip({ status }: { status: string }) {
  const variant = status === "active" ? "enrolled" : status === "paused" ? "paused" : "expired";
  return <Chip variant={variant} label={status.toUpperCase()} />;
}

function CopyIdButton({ id, label }: { id: string; label: string }) {
  const [copied, setCopied] = useState(false);
  useEffect(() => {
    if (!copied) return;
    const t = window.setTimeout(() => setCopied(false), 1500);
    return () => window.clearTimeout(t);
  }, [copied]);

  return (
    <button
      type="button"
      aria-label={`Copy ${label}`}
      onClick={async () => {
        try {
          await navigator.clipboard.writeText(id);
          setCopied(true);
        } catch {
          // ignore — clipboard may be unavailable in some browsers
        }
      }}
      className="inline-flex items-center gap-1 font-mono text-[10px] font-bold tracking-overline rounded-md border border-rally-line bg-white px-2 py-0.5 text-rally-muted hover:bg-neutral-50 focus:outline-none focus:ring-2 focus:ring-rally-cobalt-600"
    >
      <Copy className="size-3" aria-hidden="true" />
      <span>{copied ? "COPIED" : label.toUpperCase()}</span>
    </button>
  );
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
  const [status, setStatus] = useState<EditableStatus>(
    (student.status as EditableStatus) ?? "active",
  );
  const [notes, setNotes] = useState(student.notes ?? "");
  const [submitError, setSubmitError] = useState<string | null>(null);
  const [submitOk, setSubmitOk] = useState(false);

  // Keep local state in sync if the server-side data refreshes.
  useEffect(() => {
    setFullName(student.full_name);
    setStatus((student.status as EditableStatus) ?? "active");
    setNotes(student.notes ?? "");
  }, [student.full_name, student.status, student.notes]);

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
      const message = err instanceof Error ? err.message : "Could not save changes.";
      setSubmitError(message);
    },
  });

  const dirty =
    fullName !== student.full_name ||
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
        if (status !== student.status) payload.status = status;
        if ((notes ?? "") !== (student.notes ?? "")) payload.notes = notes || null;
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
          icon={mutation.isPending ? <RefreshCw className="size-3.5 animate-spin" /> : undefined}
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
