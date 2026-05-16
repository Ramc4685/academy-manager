"use client";

import { useState } from "react";
import { useParams } from "next/navigation";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import * as Dialog from "@radix-ui/react-dialog";

import {
  listAdminSessions,
  listSessionEnrollments,
  listSessionWaitlist,
  createEnrollment,
  deleteEnrollment,
  pauseEnrollment,
  resumeEnrollment,
  deleteAdminSession,
  promoteWaitlist,
  skipWaitlistEntry,
  deleteWaitlistEntry,
  type AdminEnrollmentView,
  type AdminWaitlistEntry,
  type CreateEnrollmentRequest,
} from "@/lib/api/admin";
import { queryKeys } from "@/lib/query/keys";

export default function AdminSessionDetailPage() {
  const params = useParams();
  const sessionId = params.id as string;
  const queryClient = useQueryClient();
  const [addOpen, setAddOpen] = useState(false);

  // Fetch the session from today's list to get metadata.
  // We use sessionDetail key for this specific query.
  const sessionsQuery = useQuery({
    queryKey: queryKeys.admin.sessionDetail(sessionId),
    queryFn: async () => {
      const today = new Date().toISOString().slice(0, 10);
      const list = await listAdminSessions(today);
      return list.sessions.find((s) => s.session_id === sessionId) ?? null;
    },
  });

  const enrollmentsQuery = useQuery({
    queryKey: queryKeys.admin.enrollments(sessionId),
    queryFn: () => listSessionEnrollments(sessionId),
  });

  const waitlistQuery = useQuery({
    queryKey: queryKeys.admin.waitlist(sessionId),
    queryFn: () => listSessionWaitlist(sessionId),
  });

  const cancelSessionMutation = useMutation({
    mutationFn: () => deleteAdminSession(sessionId),
    onSuccess: () => {
      window.location.href = "/admin/sessions";
    },
  });

  const promoteMutation = useMutation({
    mutationFn: () => promoteWaitlist(sessionId),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: queryKeys.admin.waitlist(sessionId) });
      void queryClient.invalidateQueries({ queryKey: queryKeys.admin.enrollments(sessionId) });
    },
  });

  const session = sessionsQuery.data;

  return (
    <section data-testid="admin-session-detail">
      {/* Header */}
      <div className="mb-6 flex flex-wrap items-start justify-between gap-4">
        <div>
          <a
            href="/admin/sessions"
            className="text-sm text-blue-600 hover:underline dark:text-blue-400"
          >
            ← Sessions
          </a>
          {sessionsQuery.isLoading ? (
            <div className="mt-1 h-8 w-48 animate-pulse rounded bg-neutral-100 dark:bg-neutral-800" />
          ) : session ? (
            <>
              <h1 className="text-2xl font-semibold">{session.title}</h1>
              <p className="text-sm text-neutral-500">
                {session.location} &middot;{" "}
                {new Date(session.start_at).toLocaleString(undefined, {
                  dateStyle: "medium",
                  timeStyle: "short",
                })}
                {" – "}
                {new Date(session.end_at).toLocaleTimeString(undefined, {
                  hour: "numeric",
                  minute: "2-digit",
                })}
              </p>
            </>
          ) : (
            <h1 className="text-2xl font-semibold">Session {sessionId.slice(0, 8)}…</h1>
          )}
        </div>
        <div className="flex gap-2">
          <button
            onClick={() => setAddOpen(true)}
            className="min-h-touch rounded-md bg-blue-600 px-4 text-sm font-medium text-white hover:bg-blue-700"
          >
            + Add to roster
          </button>
          <button
            onClick={() => {
              if (confirm("Cancel this session? This cannot be undone.")) {
                cancelSessionMutation.mutate();
              }
            }}
            disabled={cancelSessionMutation.isPending}
            className="min-h-touch rounded-md border border-red-300 px-4 text-sm text-red-600 hover:bg-red-50 dark:border-red-700 dark:text-red-400 disabled:opacity-60"
          >
            {cancelSessionMutation.isPending ? "Cancelling…" : "Cancel session"}
          </button>
        </div>
      </div>

      {/* Roster table */}
      <div className="mb-8">
        <div className="mb-3 flex items-center justify-between">
          <h2 className="text-lg font-semibold">Roster</h2>
          {session && (
            <span className="text-sm text-neutral-500">
              {enrollmentsQuery.data?.enrollments.length ?? "…"}/{session.capacity}
            </span>
          )}
        </div>
        {enrollmentsQuery.isLoading ? (
          <TableSkeleton />
        ) : (enrollmentsQuery.data?.enrollments.length ?? 0) === 0 ? (
          <p className="text-sm text-neutral-500" data-testid="roster-empty">
            No enrolled students.
          </p>
        ) : (
          <RosterTable
            enrollments={enrollmentsQuery.data!.enrollments}
            onDelete={(id) => {
              if (confirm("Remove this enrollment?")) {
                deleteEnrollment(id).then(() =>
                  queryClient.invalidateQueries({
                    queryKey: queryKeys.admin.enrollments(sessionId),
                  })
                );
              }
            }}
            onPause={(id) =>
              pauseEnrollment(id).then(() =>
                queryClient.invalidateQueries({
                  queryKey: queryKeys.admin.enrollments(sessionId),
                })
              )
            }
            onResume={(id) =>
              resumeEnrollment(id).then(() =>
                queryClient.invalidateQueries({
                  queryKey: queryKeys.admin.enrollments(sessionId),
                })
              )
            }
          />
        )}
      </div>

      {/* Waitlist table */}
      <div>
        <div className="mb-3 flex items-center justify-between">
          <h2 className="text-lg font-semibold">Waitlist</h2>
          <button
            onClick={() => promoteMutation.mutate()}
            disabled={
              promoteMutation.isPending ||
              (waitlistQuery.data?.waitlist.filter((w) => w.status === "waiting").length ?? 0) === 0
            }
            className="min-h-touch rounded-md bg-emerald-600 px-3 text-sm font-medium text-white hover:bg-emerald-700 disabled:opacity-50"
          >
            Promote next
          </button>
        </div>
        {waitlistQuery.isLoading ? (
          <TableSkeleton />
        ) : (waitlistQuery.data?.waitlist.length ?? 0) === 0 ? (
          <p className="text-sm text-neutral-500" data-testid="waitlist-empty">
            Waitlist is empty.
          </p>
        ) : (
          <WaitlistTable
            entries={waitlistQuery.data!.waitlist}
            onSkip={(id) =>
              skipWaitlistEntry(id).then(() =>
                queryClient.invalidateQueries({ queryKey: queryKeys.admin.waitlist(sessionId) })
              )
            }
            onRemove={(id) => {
              if (confirm("Remove from waitlist?")) {
                deleteWaitlistEntry(id).then(() =>
                  queryClient.invalidateQueries({
                    queryKey: queryKeys.admin.waitlist(sessionId),
                  })
                );
              }
            }}
          />
        )}
      </div>

      <AddToRosterDialog
        open={addOpen}
        onOpenChange={setAddOpen}
        sessionId={sessionId}
        onAdded={() => {
          setAddOpen(false);
          void queryClient.invalidateQueries({
            queryKey: queryKeys.admin.enrollments(sessionId),
          });
        }}
      />
    </section>
  );
}

// ---------------------------------------------------------------------------
// Roster table
// ---------------------------------------------------------------------------

function RosterTable({
  enrollments,
  onDelete,
  onPause,
  onResume,
}: {
  enrollments: AdminEnrollmentView[];
  onDelete: (id: string) => void;
  onPause: (id: string) => void;
  onResume: (id: string) => void;
}) {
  return (
    <div className="overflow-x-auto rounded-lg border border-neutral-200 dark:border-neutral-800">
      <table className="w-full text-sm bg-white dark:bg-neutral-900">
        <thead>
          <tr className="border-b border-neutral-200 dark:border-neutral-700 text-left text-neutral-500">
            <th className="px-4 py-3 font-medium">Name</th>
            <th className="px-4 py-3 font-medium">Status</th>
            <th className="px-4 py-3 font-medium">Enrolled</th>
            <th className="px-4 py-3 font-medium sr-only">Actions</th>
          </tr>
        </thead>
        <tbody>
          {enrollments.map((e) => (
            <tr
              key={e.enrollment_id}
              data-testid={`enrollment-row-${e.enrollment_id}`}
              className="border-b border-neutral-100 dark:border-neutral-800 last:border-0"
            >
              <td className="px-4 py-3 font-medium">{e.full_name}</td>
              <td className="px-4 py-3">
                <EnrollmentStatusBadge status={e.status} />
              </td>
              <td className="px-4 py-3 text-neutral-500">
                {new Date(e.enrolled_at).toLocaleDateString()}
              </td>
              <td className="px-4 py-3">
                <div className="flex items-center gap-2 justify-end">
                  {e.status === "active" ? (
                    <button
                      onClick={() => onPause(e.enrollment_id)}
                      className="min-h-touch rounded-md border border-amber-300 px-2 text-xs text-amber-700 hover:bg-amber-50 dark:border-amber-700 dark:text-amber-400"
                    >
                      Pause
                    </button>
                  ) : e.status === "paused" ? (
                    <button
                      onClick={() => onResume(e.enrollment_id)}
                      className="min-h-touch rounded-md border border-green-300 px-2 text-xs text-green-700 hover:bg-green-50 dark:border-green-700 dark:text-green-400"
                    >
                      Resume
                    </button>
                  ) : null}
                  <button
                    onClick={() => onDelete(e.enrollment_id)}
                    className="min-h-touch rounded-md border border-red-200 px-2 text-xs text-red-600 hover:bg-red-50 dark:border-red-800 dark:text-red-400"
                    aria-label={`Remove ${e.full_name}`}
                  >
                    Remove
                  </button>
                </div>
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

function EnrollmentStatusBadge({ status }: { status: string }) {
  const colors: Record<string, string> = {
    active: "bg-green-100 text-green-800 dark:bg-green-900 dark:text-green-200",
    paused: "bg-amber-100 text-amber-800 dark:bg-amber-900 dark:text-amber-200",
    cancelled: "bg-neutral-100 text-neutral-600 dark:bg-neutral-800 dark:text-neutral-300",
  };
  return (
    <span
      className={`inline-block rounded-full px-2 py-0.5 text-xs font-medium ${
        colors[status] ?? "bg-neutral-100 text-neutral-600"
      }`}
    >
      {status}
    </span>
  );
}

// ---------------------------------------------------------------------------
// Waitlist table
// ---------------------------------------------------------------------------

function WaitlistTable({
  entries,
  onSkip,
  onRemove,
}: {
  entries: AdminWaitlistEntry[];
  onSkip: (id: string) => void;
  onRemove: (id: string) => void;
}) {
  return (
    <div className="overflow-x-auto rounded-lg border border-neutral-200 dark:border-neutral-800">
      <table className="w-full text-sm bg-white dark:bg-neutral-900">
        <thead>
          <tr className="border-b border-neutral-200 dark:border-neutral-700 text-left text-neutral-500">
            <th className="px-4 py-3 font-medium">#</th>
            <th className="px-4 py-3 font-medium">Name</th>
            <th className="px-4 py-3 font-medium">Status</th>
            <th className="px-4 py-3 font-medium sr-only">Actions</th>
          </tr>
        </thead>
        <tbody>
          {entries.map((w) => (
            <tr
              key={w.waitlist_id}
              data-testid={`waitlist-row-${w.waitlist_id}`}
              className="border-b border-neutral-100 dark:border-neutral-800 last:border-0"
            >
              <td className="px-4 py-3 tabular-nums text-neutral-500">{w.position}</td>
              <td className="px-4 py-3 font-medium">{w.full_name}</td>
              <td className="px-4 py-3">
                <WaitlistStatusBadge status={w.status} />
              </td>
              <td className="px-4 py-3">
                <div className="flex items-center gap-2 justify-end">
                  {w.status === "waiting" && (
                    <button
                      onClick={() => onSkip(w.waitlist_id)}
                      className="min-h-touch rounded-md border border-neutral-300 px-2 text-xs hover:bg-neutral-50 dark:border-neutral-700"
                    >
                      Skip
                    </button>
                  )}
                  <button
                    onClick={() => onRemove(w.waitlist_id)}
                    className="min-h-touch rounded-md border border-red-200 px-2 text-xs text-red-600 hover:bg-red-50 dark:border-red-800 dark:text-red-400"
                    aria-label={`Remove ${w.full_name} from waitlist`}
                  >
                    Remove
                  </button>
                </div>
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

function WaitlistStatusBadge({ status }: { status: string }) {
  const colors: Record<string, string> = {
    waiting: "bg-amber-100 text-amber-800 dark:bg-amber-900 dark:text-amber-200",
    promoted: "bg-green-100 text-green-800 dark:bg-green-900 dark:text-green-200",
    skipped: "bg-neutral-100 text-neutral-600 dark:bg-neutral-800 dark:text-neutral-300",
    removed: "bg-red-100 text-red-700 dark:bg-red-900 dark:text-red-300",
  };
  return (
    <span
      className={`inline-block rounded-full px-2 py-0.5 text-xs font-medium ${
        colors[status] ?? "bg-neutral-100 text-neutral-600"
      }`}
    >
      {status}
    </span>
  );
}

// ---------------------------------------------------------------------------
// Add to roster dialog
// ---------------------------------------------------------------------------

const EMPTY_ADD: CreateEnrollmentRequest = {
  session_id: "",
  student_id: "",
  parent_id: "",
  full_name: "",
};

function AddToRosterDialog({
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

  const mutation = useMutation({
    mutationFn: (payload: CreateEnrollmentRequest) => createEnrollment(payload),
    onSuccess: () => {
      setForm({ student_id: "", parent_id: "", full_name: "" });
      setError(null);
      onAdded();
    },
    onError: (err: Error) => {
      setError(err.message ?? "Failed to enroll student.");
    },
  });

  const handleSubmit = (e: React.FormEvent) => {
    e.preventDefault();
    mutation.mutate({ ...form, session_id: sessionId });
  };

  return (
    <Dialog.Root open={open} onOpenChange={onOpenChange}>
      <Dialog.Portal>
        <Dialog.Overlay className="fixed inset-0 z-50 bg-black/40" />
        <Dialog.Content
          className="fixed left-1/2 top-1/2 z-50 w-full max-w-sm -translate-x-1/2 -translate-y-1/2 rounded-xl bg-white dark:bg-neutral-900 p-6 shadow-xl focus:outline-none"
          aria-describedby="add-roster-desc"
        >
          <Dialog.Title className="text-lg font-semibold mb-1">Add to roster</Dialog.Title>
          <Dialog.Description id="add-roster-desc" className="text-sm text-neutral-500 mb-4">
            Directly enroll a student into this session.
          </Dialog.Description>

          {error && (
            <p role="alert" className="mb-3 rounded-md bg-red-50 p-2 text-sm text-red-700 dark:bg-red-950 dark:text-red-300">
              {error}
            </p>
          )}

          <form onSubmit={handleSubmit} className="space-y-3">
            <Field label="Full name" required>
              <input
                type="text"
                required
                value={form.full_name}
                onChange={(e) => setForm((f) => ({ ...f, full_name: e.target.value }))}
                className={inputClass}
              />
            </Field>
            <Field label="Student ID" required>
              <input
                type="text"
                required
                value={form.student_id}
                onChange={(e) => setForm((f) => ({ ...f, student_id: e.target.value }))}
                className={inputClass}
                placeholder="uid-…"
              />
            </Field>
            <Field label="Parent ID" required>
              <input
                type="text"
                required
                value={form.parent_id}
                onChange={(e) => setForm((f) => ({ ...f, parent_id: e.target.value }))}
                className={inputClass}
                placeholder="uid-…"
              />
            </Field>
            <div className="flex justify-end gap-2 pt-2">
              <Dialog.Close asChild>
                <button
                  type="button"
                  className="min-h-touch rounded-md border border-neutral-300 px-4 text-sm dark:border-neutral-700"
                >
                  Cancel
                </button>
              </Dialog.Close>
              <button
                type="submit"
                disabled={mutation.isPending}
                className="min-h-touch rounded-md bg-blue-600 px-4 text-sm font-medium text-white hover:bg-blue-700 disabled:opacity-60"
              >
                {mutation.isPending ? "Enrolling…" : "Enroll"}
              </button>
            </div>
          </form>
        </Dialog.Content>
      </Dialog.Portal>
    </Dialog.Root>
  );
}

const inputClass =
  "w-full rounded-md border border-neutral-300 dark:border-neutral-700 bg-white dark:bg-neutral-900 px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500";

function Field({
  label,
  required,
  children,
}: {
  label: string;
  required?: boolean;
  children: React.ReactNode;
}) {
  return (
    <label className="block">
      <span className="mb-1 block text-sm font-medium text-neutral-700 dark:text-neutral-300">
        {label}
        {required && <span aria-hidden="true" className="ml-0.5 text-red-500">*</span>}
      </span>
      {children}
    </label>
  );
}

function TableSkeleton() {
  return (
    <div className="space-y-2">
      {[0, 1, 2].map((i) => (
        <div
          key={i}
          className="h-12 animate-pulse rounded-lg bg-neutral-100 dark:bg-neutral-800"
        />
      ))}
    </div>
  );
}
