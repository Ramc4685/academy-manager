"use client";

/**
 * Admin session detail — Rally restyle.
 *
 * Preserves: roster table with pause/resume/move/remove, waitlist with
 * skip/remove + "promote next", add-to-roster dialog, transfer dialog,
 * cancel session.
 */

import { useState } from "react";
import Link from "next/link";
import { useParams } from "next/navigation";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import * as Dialog from "@radix-ui/react-dialog";

import {
  listAdminSessions,
  listAdminStudents,
  listSessionEnrollments,
  listSessionWaitlist,
  createEnrollment,
  deleteEnrollment,
  pauseEnrollment,
  resumeEnrollment,
  transferEnrollment,
  deleteAdminSession,
  promoteWaitlist,
  approveWithdrawalCredit,
  previewWithdrawalCredit,
  quoteAdminEnrollment,
  skipWaitlistEntry,
  deleteWaitlistEntry,
  type AdminEnrollmentView,
  type AdminEnrollmentQuote,
  type EnrollmentStatus,
  type AdminSessionView,
  type AdminStudentView,
  type AdminWaitlistEntry,
  type WaitlistStatus,
  type CreateEnrollmentRequest,
} from "@/lib/api/admin";
import { queryKeys } from "@/lib/query/keys";

import { Avatar } from "@/components/ds/avatar";
import { Button } from "@/components/ds/button";
import { Card } from "@/components/ds/card";
import { Chip, type ChipVariant } from "@/components/ds/chip";
import { Icon } from "@/components/ds/icons";
import { LaneHeader } from "@/components/ds/lane";
import { Overline } from "@/components/ds/typography";

const ENROLL_CHIP: Record<EnrollmentStatus, { variant: ChipVariant; label: string }> = {
  active: { variant: "enrolled", label: "ACTIVE" },
  paused: { variant: "paused", label: "PAUSED" },
  cancelled: { variant: "expired", label: "CANCELLED" },
  withdrawn: { variant: "expired", label: "WITHDRAWN" },
};

const WAITLIST_CHIP: Record<WaitlistStatus, { variant: ChipVariant; label: string }> = {
  waiting: { variant: "waitlist", label: "WAITING" },
  promoted: { variant: "enrolled", label: "PROMOTED" },
  skipped: { variant: "expired", label: "SKIPPED" },
  removed: { variant: "expired", label: "REMOVED" },
};

export default function AdminSessionDetailPage() {
  const params = useParams();
  const sessionId = params.id as string;
  const queryClient = useQueryClient();
  const [addOpen, setAddOpen] = useState(false);
  const [transferTarget, setTransferTarget] = useState<AdminEnrollmentView | null>(null);
  const [withdrawalTarget, setWithdrawalTarget] = useState<AdminEnrollmentView | null>(null);

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
  const enrollments = enrollmentsQuery.data?.enrollments ?? [];
  const waitlist = waitlistQuery.data?.waitlist ?? [];
  const waitingCount = waitlist.filter((w) => w.status === "waiting").length;

  return (
    <section data-testid="admin-session-detail" className="space-y-6">
      {/* Header */}
      <div className="flex flex-wrap items-start justify-between gap-4">
        <div>
          <Link
            href="/admin/sessions"
            className="inline-flex items-center gap-1 font-mono text-[10px] font-bold uppercase tracking-overline text-rally-muted hover:text-rally-ink"
          >
            ← Sessions
          </Link>
          {sessionsQuery.isLoading ? (
            <div className="mt-2 h-8 w-48 animate-pulse rounded bg-rally-line/40" />
          ) : session ? (
            <>
              <h1 className="mt-1 font-display text-[24px] font-semibold tracking-[-0.02em] text-rally-ink">
                {session.title}
              </h1>
              <p className="mt-1 text-sm text-rally-muted">
                {session.location} · {new Date(session.start_at).toLocaleString(undefined, { dateStyle: "medium", timeStyle: "short" })}
                {" – "}
                {new Date(session.end_at).toLocaleTimeString(undefined, { hour: "numeric", minute: "2-digit" })}
                {session.coach_name ? ` · Coach ${session.coach_name}` : ""}
              </p>
            </>
          ) : (
            <h1 className="font-display text-2xl font-semibold text-rally-ink">
              Session {sessionId.slice(0, 8)}…
            </h1>
          )}
        </div>
        <div className="flex gap-2">
          <Button
            variant="primary"
            size="sm"
            icon={Icon.plus(14, "currentColor")}
            onClick={() => setAddOpen(true)}
          >
            Add to roster
          </Button>
          <Button
            variant="danger"
            size="sm"
            onClick={() => {
              if (confirm("Cancel this session? This cannot be undone.")) {
                cancelSessionMutation.mutate();
              }
            }}
            disabled={cancelSessionMutation.isPending}
          >
            {cancelSessionMutation.isPending ? "Cancelling…" : "Cancel session"}
          </Button>
        </div>
      </div>

      {/* Roster */}
      <Card p={20}>
        <LaneHeader
          index="01"
          title="Roster"
          action={
            session && (
              <span className="font-mono text-sm font-semibold tabular-nums text-rally-muted">
                {enrollments.length}/{session.capacity}
              </span>
            )
          }
        />
        {enrollmentsQuery.isLoading ? (
          <TableSkeleton />
        ) : enrollments.length === 0 ? (
          <p className="text-sm text-rally-subtle" data-testid="roster-empty">No enrolled students.</p>
        ) : (
          <RosterTable
            enrollments={enrollments}
            onDelete={(id) => {
              if (confirm("Remove this enrollment?")) {
                deleteEnrollment(id).then(() =>
                  queryClient.invalidateQueries({ queryKey: queryKeys.admin.enrollments(sessionId) })
                );
              }
            }}
            onPause={(id) =>
              pauseEnrollment(id).then(() =>
                queryClient.invalidateQueries({ queryKey: queryKeys.admin.enrollments(sessionId) })
              )
            }
            onResume={(id) =>
              resumeEnrollment(id).then(() =>
                queryClient.invalidateQueries({ queryKey: queryKeys.admin.enrollments(sessionId) })
              )
            }
            onTransfer={(enrollment) => setTransferTarget(enrollment)}
            onWithdraw={(enrollment) => setWithdrawalTarget(enrollment)}
          />
        )}
      </Card>

      {/* Waitlist */}
      <Card p={20}>
        <LaneHeader
          index="02"
          title="Waitlist"
          action={
            <Button
              variant="volt"
              size="sm"
              onClick={() => promoteMutation.mutate()}
              disabled={promoteMutation.isPending || waitingCount === 0}
            >
              Promote next
            </Button>
          }
        />
        {waitlistQuery.isLoading ? (
          <TableSkeleton />
        ) : waitlist.length === 0 ? (
          <p className="text-sm text-rally-subtle" data-testid="waitlist-empty">Waitlist is empty.</p>
        ) : (
          <WaitlistTable
            entries={waitlist}
            onSkip={(id) =>
              skipWaitlistEntry(id).then(() =>
                queryClient.invalidateQueries({ queryKey: queryKeys.admin.waitlist(sessionId) })
              )
            }
            onRemove={(id) => {
              if (confirm("Remove from waitlist?")) {
                deleteWaitlistEntry(id).then(() =>
                  queryClient.invalidateQueries({ queryKey: queryKeys.admin.waitlist(sessionId) })
                );
              }
            }}
          />
        )}
      </Card>

      <AddToRosterDialog
        open={addOpen}
        onOpenChange={setAddOpen}
        sessionId={sessionId}
        onAdded={() => {
          setAddOpen(false);
          void queryClient.invalidateQueries({ queryKey: queryKeys.admin.enrollments(sessionId) });
        }}
      />
      <TransferEnrollmentDialog
        enrollment={transferTarget}
        currentSessionId={sessionId}
        currentSessionTitle={session?.title ?? ""}
        onClose={() => setTransferTarget(null)}
        onMoved={() => {
          setTransferTarget(null);
          void queryClient.invalidateQueries({ queryKey: queryKeys.admin.enrollments(sessionId) });
          void queryClient.invalidateQueries({ queryKey: queryKeys.admin.sessions() });
        }}
      />
      <WithdrawalCreditDialog
        enrollment={withdrawalTarget}
        onClose={() => setWithdrawalTarget(null)}
        onApproved={() => {
          setWithdrawalTarget(null);
          void queryClient.invalidateQueries({
            queryKey: queryKeys.admin.enrollments(sessionId),
          });
        }}
      />
    </section>
  );
}

// ─────────────────────────────────────────────────────────────────────────────
// Roster table
// ─────────────────────────────────────────────────────────────────────────────

function RosterTable({
  enrollments,
  onDelete,
  onPause,
  onResume,
  onTransfer,
  onWithdraw,
}: {
  enrollments: AdminEnrollmentView[];
  onDelete: (id: string) => void;
  onPause: (id: string) => void;
  onResume: (id: string) => void;
  onTransfer: (enrollment: AdminEnrollmentView) => void;
  onWithdraw: (enrollment: AdminEnrollmentView) => void;
}) {
  return (
    <div className="overflow-x-auto">
      <table className="w-full text-sm">
        <thead>
          <tr className="border-b border-rally-line text-left">
            <Th>Name</Th>
            <Th>Status</Th>
            <Th>Enrolled</Th>
            <Th><span className="sr-only">Actions</span></Th>
          </tr>
        </thead>
        <tbody>
          {enrollments.map((e) => {
            const chip = ENROLL_CHIP[e.status];
            return (
              <tr
                key={e.enrollment_id}
                data-testid={`enrollment-row-${e.enrollment_id}`}
                className="border-b border-rally-line/60 last:border-0"
              >
                <td className="px-4 py-3">
                  <div className="flex items-center gap-2">
                    <Avatar name={e.full_name} size={28} />
                    <span className="font-display font-semibold text-rally-ink">{e.full_name}</span>
                  </div>
                </td>
                <td className="px-4 py-3">
                  <Chip variant={chip.variant} label={chip.label} />
                </td>
                <td className="px-4 py-3 font-mono text-rally-muted">
                  {new Date(e.enrolled_at).toLocaleDateString()}
                </td>
                <td className="px-4 py-3">
                  <div className="flex items-center gap-2 justify-end">
                    {e.status === "active" ? (
                      <Button variant="secondary" size="sm" onClick={() => onPause(e.enrollment_id)}>
                        Pause
                      </Button>
                    ) : e.status === "paused" ? (
                      <Button variant="secondary" size="sm" onClick={() => onResume(e.enrollment_id)}>
                        Resume
                      </Button>
                    ) : null}
                    <Button variant="secondary" size="sm" onClick={() => onTransfer(e)}>
                      Move
                    </Button>
                    {e.status === "active" && (
                      <Button variant="secondary" size="sm" onClick={() => onWithdraw(e)}>
                        Withdraw
                      </Button>
                    )}
                    <Button
                      variant="danger"
                      size="sm"
                      onClick={() => onDelete(e.enrollment_id)}
                      aria-label={`Remove ${e.full_name}`}
                    >
                      Remove
                    </Button>
                  </div>
                </td>
              </tr>
            );
          })}
        </tbody>
      </table>
    </div>
  );
}

// ─────────────────────────────────────────────────────────────────────────────
// Waitlist table
// ─────────────────────────────────────────────────────────────────────────────

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
    <div className="overflow-x-auto">
      <table className="w-full text-sm">
        <thead>
          <tr className="border-b border-rally-line text-left">
            <Th>#</Th>
            <Th>Name</Th>
            <Th>Status</Th>
            <Th><span className="sr-only">Actions</span></Th>
          </tr>
        </thead>
        <tbody>
          {entries.map((w) => {
            const chip = WAITLIST_CHIP[w.status];
            return (
              <tr
                key={w.waitlist_id}
                data-testid={`waitlist-row-${w.waitlist_id}`}
                className="border-b border-rally-line/60 last:border-0"
              >
                <td className="px-4 py-3 font-mono tabular-nums text-rally-muted">{w.position}</td>
                <td className="px-4 py-3 font-display font-semibold text-rally-ink">{w.full_name}</td>
                <td className="px-4 py-3">
                  <Chip variant={chip.variant} label={chip.label} />
                </td>
                <td className="px-4 py-3">
                  <div className="flex items-center gap-2 justify-end">
                    {w.status === "waiting" && (
                      <Button variant="secondary" size="sm" onClick={() => onSkip(w.waitlist_id)}>
                        Skip
                      </Button>
                    )}
                    <Button
                      variant="danger"
                      size="sm"
                      onClick={() => onRemove(w.waitlist_id)}
                      aria-label={`Remove ${w.full_name} from waitlist`}
                    >
                      Remove
                    </Button>
                  </div>
                </td>
              </tr>
            );
          })}
        </tbody>
      </table>
    </div>
  );
}

// ─────────────────────────────────────────────────────────────────────────────
// Add-to-roster dialog
// ─────────────────────────────────────────────────────────────────────────────

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
            <Field label="Student ID" required>
              <input
                type="text"
                required
                value={form.student_id}
                onChange={(e) => setForm((f) => ({ ...f, student_id: e.target.value }))}
                className={inputClass}
                placeholder={studentsQuery.isLoading ? "Loading students…" : "Student Mongo ID"}
              />
            </Field>
            <Field label="Parent ID" required>
              <input
                type="text"
                required
                value={form.parent_id}
                onChange={(e) => setForm((f) => ({ ...f, parent_id: e.target.value }))}
                className={inputClass}
                placeholder="Parent Mongo ID"
              />
            </Field>
          </>
        )}
        <DialogActions>
          <Dialog.Close asChild>
            <Button variant="secondary" size="sm" type="button">Cancel</Button>
          </Dialog.Close>
          <Button variant="primary" size="sm" type="submit" disabled={mutation.isPending}>
            {mutation.isPending ? "Enrolling…" : "Enroll"}
          </Button>
        </DialogActions>
      </form>
    </RallyDialog>
  );
}

// ─────────────────────────────────────────────────────────────────────────────
// Transfer enrollment dialog
// ─────────────────────────────────────────────────────────────────────────────

function TransferEnrollmentDialog({
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
      transferEnrollment(enrollment!.enrollment_id, { target_session_id: targetSessionId }),
    onSuccess: () => {
      setTargetSessionId("");
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
        <DialogActions>
          <Button variant="secondary" size="sm" type="button" onClick={onClose}>
            Cancel
          </Button>
          <Button
            variant="primary"
            size="sm"
            type="submit"
            disabled={
              mutation.isPending || candidateSessions.length === 0 || !targetSessionId
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
function RallySessionPicker({
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

function RallyDialog({
  open,
  onOpenChange,
  title,
  description,
  overline,
  children,
}: {
  open: boolean;
  onOpenChange: (v: boolean) => void;
  title: string;
  description: string;
  overline: string;
  children: React.ReactNode;
}) {
  return (
    <Dialog.Root open={open} onOpenChange={onOpenChange}>
      <Dialog.Portal>
        <Dialog.Overlay className="fixed inset-0 z-50 bg-rally-ink/40" />
        <Dialog.Content className="fixed left-1/2 top-1/2 z-50 w-full max-w-md -translate-x-1/2 -translate-y-1/2 rounded-xl bg-white p-6 shadow-xl focus:outline-none">
          <Overline>{overline}</Overline>
          <Dialog.Title className="mt-1 font-display text-xl font-semibold tracking-[-0.01em]">
            {title}
          </Dialog.Title>
          {description && (
            <Dialog.Description className="mt-1 mb-4 text-sm text-rally-muted">
              {description}
            </Dialog.Description>
          )}
          {children}
        </Dialog.Content>
      </Dialog.Portal>
    </Dialog.Root>
  );
}

function DialogError({ message }: { message: string }) {
  return (
    <p role="alert" className="mb-3 rounded-md bg-red-50 px-3 py-2 text-sm text-red-700">
      {message}
    </p>
  );
}

function DialogActions({ children }: { children: React.ReactNode }) {
  return <div className="flex justify-end gap-2 pt-2">{children}</div>;
}

function WithdrawalCreditDialog({
  enrollment,
  onClose,
  onApproved,
}: {
  enrollment: AdminEnrollmentView | null;
  onClose: () => void;
  onApproved: () => void;
}) {
  const [withdrawalDate, setWithdrawalDate] = useState(() => new Date().toISOString().slice(0, 10));
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
    mutationFn: () =>
      approveWithdrawalCredit(enrollment!.enrollment_id, {
        withdrawal_date: `${withdrawalDate}T00:00:00.000Z`,
        admin_note: adminNote,
      }),
    onSuccess: () => {
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
            <button
              type="button"
              disabled={!withdrawalDate || previewMutation.isPending}
              onClick={() => previewMutation.mutate()}
              className="min-h-touch rounded-md border border-blue-300 px-3 text-sm font-medium text-blue-700 hover:bg-blue-50 disabled:opacity-60 dark:border-blue-700 dark:text-blue-300"
            >
              {previewMutation.isPending ? "Previewing..." : "Preview credit"}
            </button>
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
                disabled={!preview || approveMutation.isPending}
                onClick={() => approveMutation.mutate()}
                className="min-h-touch rounded-md bg-orange-600 px-4 text-sm font-medium text-white hover:bg-orange-700 disabled:opacity-60"
              >
                {approveMutation.isPending ? "Approving..." : "Approve withdrawal"}
              </button>
            </div>
          </div>
        </Dialog.Content>
      </Dialog.Portal>
    </Dialog.Root>
  );
}

function StudentSelect({
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

const inputClass =
  "w-full rounded-md border border-rally-line bg-white px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-rally-cobalt-600/30";

function formatCents(cents: number): string {
  return new Intl.NumberFormat("en-US", { style: "currency", currency: "USD" }).format(cents / 100);
}

function formatShortDateTime(value: string): string {
  return new Date(value).toLocaleString(undefined, {
    month: "short",
    day: "numeric",
    hour: "numeric",
    minute: "2-digit",
  });
}

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
      <span className="mb-1 block font-mono text-[10px] font-bold uppercase tracking-overline text-rally-muted">
        {label}
        {required && <span aria-hidden="true" className="ml-1 text-red-500">*</span>}
      </span>
      {children}
    </label>
  );
}

function Th({ children }: { children: React.ReactNode }) {
  return (
    <th className="px-4 py-3 text-left font-mono text-[10px] font-bold uppercase tracking-overline text-rally-muted">
      {children}
    </th>
  );
}

function TableSkeleton() {
  return (
    <div className="space-y-2">
      {[0, 1, 2].map((i) => (
        <div key={i} className="h-12 animate-pulse rounded-xl bg-rally-line/40" />
      ))}
    </div>
  );
}
