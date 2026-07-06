"use client";

import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import {
  approveMakeup,
  approveTrial,
  denyMakeup,
  denyTrial,
  listAdminAbsences,
  listAdminCancellations,
  listAdminMakeups,
  listAdminTrials,
  listSessionOccurrences,
  type AbsenceNoticeAdminRow,
  type AdminSessionOccurrenceView,
  type MakeupRequestAdminRow,
  type SelfCancellationAdminRow,
  type TrialRequestAdminRow,
} from "@/lib/api/admin";
import { queryKeys } from "@/lib/query/keys";
import { formatAcademyDateTime } from "@/lib/format/academy-time";
import { Card } from "@/components/ds/card";
import { Chip, type ChipVariant } from "@/components/ds/chip";
import { Button } from "@/components/ds/button";

type RequestTab = "makeups" | "trials" | "absences" | "cancellations";

const TABS: { id: RequestTab; label: string }[] = [
  { id: "makeups", label: "Makeups" },
  { id: "trials", label: "Trials" },
  { id: "absences", label: "Absences" },
  { id: "cancellations", label: "Cancellations" },
];

type StatusFilter = "all" | "pending" | "approved" | "denied" | "expired" | "converted";

const MAKEUP_STATUS_FILTERS: StatusFilter[] = ["all", "pending", "approved", "denied", "expired"];
const TRIAL_STATUS_FILTERS: StatusFilter[] = ["all", "pending", "approved", "denied", "converted"];

function statusChipVariant(status: string): ChipVariant {
  switch (status) {
    case "approved":
      return "approved";
    case "denied":
      return "denied";
    case "expired":
      return "expired";
    case "converted":
      return "converted";
    default:
      return "pending";
  }
}

export default function AdminRequestsPage() {
  const [tab, setTab] = useState<RequestTab>("makeups");

  return (
    <section data-testid="admin-requests" className="space-y-6">
      <div>
        <h1 className="font-display text-2xl font-bold tracking-tight text-rally-ink">Requests</h1>
        <p className="mt-0.5 text-sm text-rally-subtle">
          Makeup, trial, absence, and cancellation requests from parents
        </p>
      </div>

      <div role="tablist" aria-label="Request type" className="flex flex-wrap gap-1 rounded-xl bg-neutral-100 p-1 dark:bg-neutral-800">
        {TABS.map((t) => (
          <button
            key={t.id}
            type="button"
            role="tab"
            aria-selected={tab === t.id}
            onClick={() => setTab(t.id)}
            className="min-h-touch flex-1 rounded-lg px-3 text-sm font-semibold transition-all duration-150"
            style={
              tab === t.id
                ? { background: "white", color: "var(--rally-ink)", boxShadow: "0 1px 2px rgba(0,0,0,0.06)" }
                : { background: "transparent", color: "var(--rally-muted)" }
            }
          >
            {t.label}
          </button>
        ))}
      </div>

      {tab === "makeups" && <MakeupsTab />}
      {tab === "trials" && <TrialsTab />}
      {tab === "absences" && <AbsencesTab />}
      {tab === "cancellations" && <CancellationsTab />}
    </section>
  );
}

function StatusFilterChips({
  value,
  options,
  onChange,
}: {
  value: StatusFilter;
  options: StatusFilter[];
  onChange: (v: StatusFilter) => void;
}) {
  return (
    <div className="flex flex-wrap gap-2" role="group" aria-label="Filter by status">
      {options.map((opt) => (
        <button
          key={opt}
          type="button"
          onClick={() => onChange(opt)}
          className="rounded-full border px-3 py-1 font-mono text-[10px] font-bold uppercase tracking-overline transition-colors"
          style={
            value === opt
              ? { background: "var(--rally-ink)", color: "white", borderColor: "var(--rally-ink)" }
              : { background: "transparent", color: "var(--rally-muted)", borderColor: "var(--rally-line)" }
          }
        >
          {opt}
        </button>
      ))}
    </div>
  );
}

// --- Makeups ---

function MakeupsTab() {
  const queryClient = useQueryClient();
  const [statusFilter, setStatusFilter] = useState<StatusFilter>("pending");
  const [denyTarget, setDenyTarget] = useState<MakeupRequestAdminRow | null>(null);
  const [approveTarget, setApproveTarget] = useState<MakeupRequestAdminRow | null>(null);

  const apiStatus = statusFilter === "all" ? undefined : statusFilter;
  const { data, isLoading, isError } = useQuery({
    queryKey: queryKeys.admin.selfServiceMakeups(apiStatus),
    queryFn: () => listAdminMakeups(apiStatus),
  });

  const approveMutation = useMutation({
    mutationFn: ({ requestId, targetOccurrenceId }: { requestId: string; targetOccurrenceId: string }) =>
      approveMakeup(requestId, { target_occurrence_id: targetOccurrenceId }),
    onSuccess: () => {
      setApproveTarget(null);
      void queryClient.invalidateQueries({ queryKey: ["admin", "self-service", "makeups"] });
    },
  });
  const denyMutation = useMutation({
    mutationFn: ({ requestId, reason }: { requestId: string; reason: string }) => denyMakeup(requestId, { reason }),
    onSuccess: () => {
      setDenyTarget(null);
      void queryClient.invalidateQueries({ queryKey: ["admin", "self-service", "makeups"] });
    },
  });

  const makeups = data?.makeups ?? [];

  return (
    <div className="space-y-4">
      <StatusFilterChips value={statusFilter} options={MAKEUP_STATUS_FILTERS} onChange={setStatusFilter} />

      {isError ? (
        <ErrorState message="Could not load makeup requests." />
      ) : isLoading ? (
        <Skeleton />
      ) : makeups.length === 0 ? (
        <EmptyState message="No makeup requests." testId="admin-makeups-empty" />
      ) : (
        <Card p={20}>
          <div className="overflow-x-auto">
            <table className="w-full min-w-[760px] text-sm">
              <thead>
                <tr className="border-b border-neutral-200 text-left dark:border-neutral-800">
                  <Th>Student</Th>
                  <Th>Missed class</Th>
                  <Th>Requested target</Th>
                  <Th>Expires</Th>
                  <Th>Status</Th>
                  <Th className="sr-only">Actions</Th>
                </tr>
              </thead>
              <tbody>
                {makeups.map((m) => (
                  <tr
                    key={m.request_id}
                    data-testid={`admin-makeups-row-${m.request_id}`}
                    className="border-b border-neutral-100 last:border-0 dark:border-neutral-800"
                  >
                    <td className="px-2 py-3 font-medium text-rally-base">
                      {m.student_full_name || m.student_id}
                    </td>
                    <td className="px-2 py-3 text-rally-subtle">{m.missed_occurrence_id}</td>
                    <td className="px-2 py-3 text-rally-subtle">
                      {m.approved_target_occurrence_id ?? m.requested_target_occurrence_id ?? "—"}
                    </td>
                    <td className="px-2 py-3 text-rally-subtle">{formatAcademyDateTime(m.expires_at, null)}</td>
                    <td className="px-2 py-3">
                      <Chip variant={statusChipVariant(m.status)} label={m.status.toUpperCase()} />
                      {m.status === "denied" && m.denial_reason && (
                        <p className="mt-1 text-xs text-rally-subtle">{m.denial_reason}</p>
                      )}
                    </td>
                    <td className="px-2 py-3">
                      {m.status === "pending" ? (
                        <div className="flex justify-end gap-2">
                          <Button variant="secondary" size="sm" onClick={() => setDenyTarget(m)}>
                            Deny
                          </Button>
                          <Button variant="primary" size="sm" onClick={() => setApproveTarget(m)}>
                            Approve
                          </Button>
                        </div>
                      ) : null}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </Card>
      )}

      {approveTarget && (
        <ApproveMakeupDialog
          request={approveTarget}
          pending={approveMutation.isPending}
          error={approveMutation.isError ? approveMutation.error : null}
          onCancel={() => setApproveTarget(null)}
          onConfirm={(targetOccurrenceId) =>
            approveMutation.mutate({ requestId: approveTarget.request_id, targetOccurrenceId })
          }
        />
      )}

      {denyTarget && (
        <DenyDialog
          title="Deny makeup request"
          pending={denyMutation.isPending}
          error={denyMutation.isError ? denyMutation.error : null}
          onCancel={() => setDenyTarget(null)}
          onConfirm={(reason) => denyMutation.mutate({ requestId: denyTarget.request_id, reason })}
        />
      )}
    </div>
  );
}

/**
 * Approve dialog for makeups. `MakeupRequestAdminRow` carries no
 * `session_id` (only `missed_occurrence_id`), so there is no admin
 * sessions/occurrences endpoint we can key off of here without adding a
 * new backend lookup. Falls back to a labeled text input for the target
 * occurrence id, per plan Task 11 guidance.
 */
function ApproveMakeupDialog({
  request,
  pending,
  error,
  onCancel,
  onConfirm,
}: {
  request: MakeupRequestAdminRow;
  pending: boolean;
  error: Error | null;
  onCancel: () => void;
  onConfirm: (targetOccurrenceId: string) => void;
}) {
  const [occurrenceId, setOccurrenceId] = useState(request.requested_target_occurrence_id ?? "");

  return (
    <DialogShell title="Approve makeup request" onCancel={onCancel}>
      <p className="text-sm text-rally-subtle">
        Student: {request.student_full_name || request.student_id}
      </p>
      <label className="block text-xs font-semibold text-rally-muted">
        Target occurrence id
        <input
          type="text"
          className="mt-1 min-h-touch w-full rounded-lg border px-3 text-sm"
          style={{ borderColor: "var(--rally-line)" }}
          value={occurrenceId}
          onChange={(e) => setOccurrenceId(e.target.value)}
          placeholder="occ_..."
          data-testid="approve-makeup-occurrence-input"
        />
      </label>
      <p className="text-xs text-rally-subtle">
        No occurrence picker is available for makeups yet — copy the occurrence id from the
        session&apos;s schedule (Admin → Sessions → occurrences) and paste it here.
      </p>
      {error && <p role="alert" className="text-sm text-red-700">{error.message}</p>}
      <div className="flex justify-end gap-2 pt-2">
        <Button variant="secondary" size="sm" onClick={onCancel} disabled={pending}>
          Cancel
        </Button>
        <Button
          variant="primary"
          size="sm"
          disabled={pending || !occurrenceId.trim()}
          onClick={() => onConfirm(occurrenceId.trim())}
        >
          {pending ? "Approving…" : "Approve"}
        </Button>
      </div>
    </DialogShell>
  );
}

// --- Trials ---

function TrialsTab() {
  const queryClient = useQueryClient();
  const [statusFilter, setStatusFilter] = useState<StatusFilter>("pending");
  const [denyTarget, setDenyTarget] = useState<TrialRequestAdminRow | null>(null);
  const [approveTarget, setApproveTarget] = useState<TrialRequestAdminRow | null>(null);

  const apiStatus = statusFilter === "all" ? undefined : statusFilter;
  const { data, isLoading, isError } = useQuery({
    queryKey: queryKeys.admin.selfServiceTrials(apiStatus),
    queryFn: () => listAdminTrials(apiStatus),
  });

  const approveMutation = useMutation({
    mutationFn: ({ requestId, occurrenceId }: { requestId: string; occurrenceId: string }) =>
      approveTrial(requestId, { occurrence_id: occurrenceId }),
    onSuccess: () => {
      setApproveTarget(null);
      void queryClient.invalidateQueries({ queryKey: ["admin", "self-service", "trials"] });
    },
  });
  const denyMutation = useMutation({
    mutationFn: ({ requestId, reason }: { requestId: string; reason: string }) => denyTrial(requestId, { reason }),
    onSuccess: () => {
      setDenyTarget(null);
      void queryClient.invalidateQueries({ queryKey: ["admin", "self-service", "trials"] });
    },
  });

  const trials = data?.trials ?? [];

  return (
    <div className="space-y-4">
      <StatusFilterChips value={statusFilter} options={TRIAL_STATUS_FILTERS} onChange={setStatusFilter} />

      {isError ? (
        <ErrorState message="Could not load trial requests." />
      ) : isLoading ? (
        <Skeleton />
      ) : trials.length === 0 ? (
        <EmptyState message="No trial requests." testId="admin-trials-empty" />
      ) : (
        <Card p={20}>
          <div className="overflow-x-auto">
            <table className="w-full min-w-[760px] text-sm">
              <thead>
                <tr className="border-b border-neutral-200 text-left dark:border-neutral-800">
                  <Th>Student</Th>
                  <Th>Preferred window</Th>
                  <Th>Assigned occurrence</Th>
                  <Th>Status</Th>
                  <Th className="sr-only">Actions</Th>
                </tr>
              </thead>
              <tbody>
                {trials.map((t) => (
                  <tr
                    key={t.request_id}
                    data-testid={`admin-trials-row-${t.request_id}`}
                    className="border-b border-neutral-100 last:border-0 dark:border-neutral-800"
                  >
                    <td className="px-2 py-3 font-medium text-rally-base">
                      {t.prospective_child_name || t.student_id || "Existing child"}
                    </td>
                    <td className="px-2 py-3 text-rally-subtle">
                      {t.preferred_start} – {t.preferred_end}
                    </td>
                    <td className="px-2 py-3 text-rally-subtle">{t.assigned_occurrence_id ?? "—"}</td>
                    <td className="px-2 py-3">
                      <Chip variant={statusChipVariant(t.status)} label={t.status.toUpperCase()} />
                      {t.status === "denied" && t.denial_reason && (
                        <p className="mt-1 text-xs text-rally-subtle">{t.denial_reason}</p>
                      )}
                    </td>
                    <td className="px-2 py-3">
                      {t.status === "pending" ? (
                        <div className="flex justify-end gap-2">
                          <Button variant="secondary" size="sm" onClick={() => setDenyTarget(t)}>
                            Deny
                          </Button>
                          <Button variant="primary" size="sm" onClick={() => setApproveTarget(t)}>
                            Approve
                          </Button>
                        </div>
                      ) : null}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </Card>
      )}

      {approveTarget && (
        <ApproveTrialDialog
          request={approveTarget}
          pending={approveMutation.isPending}
          error={approveMutation.isError ? approveMutation.error : null}
          onCancel={() => setApproveTarget(null)}
          onConfirm={(occurrenceId) =>
            approveMutation.mutate({ requestId: approveTarget.request_id, occurrenceId })
          }
        />
      )}

      {denyTarget && (
        <DenyDialog
          title="Deny trial request"
          pending={denyMutation.isPending}
          error={denyMutation.isError ? denyMutation.error : null}
          onCancel={() => setDenyTarget(null)}
          onConfirm={(reason) => denyMutation.mutate({ requestId: denyTarget.request_id, reason })}
        />
      )}
    </div>
  );
}

/**
 * Approve dialog for trials. Unlike makeups, `TrialRequestAdminRow` carries
 * `requested_session_id`, so we can reuse the existing admin
 * sessions/occurrences endpoint (`listSessionOccurrences`, same one the
 * admin sessions detail page uses) to present a real picker instead of a
 * free-text input.
 */
function ApproveTrialDialog({
  request,
  pending,
  error,
  onCancel,
  onConfirm,
}: {
  request: TrialRequestAdminRow;
  pending: boolean;
  error: Error | null;
  onCancel: () => void;
  onConfirm: (occurrenceId: string) => void;
}) {
  const [occurrenceId, setOccurrenceId] = useState("");
  const occurrencesQuery = useQuery({
    queryKey: queryKeys.admin.sessionOccurrences(request.requested_session_id),
    queryFn: () => listSessionOccurrences(request.requested_session_id),
  });
  const occurrences = occurrencesQuery.data?.occurrences ?? [];

  return (
    <DialogShell title="Approve trial request" onCancel={onCancel}>
      <p className="text-sm text-rally-subtle">
        {request.prospective_child_name || request.student_id || "Existing child"} · preferred{" "}
        {request.preferred_start} – {request.preferred_end}
      </p>
      <label className="block text-xs font-semibold text-rally-muted">
        Occurrence
        <select
          className="mt-1 min-h-touch w-full rounded-lg border px-3 text-sm"
          style={{ borderColor: "var(--rally-line)" }}
          value={occurrenceId}
          onChange={(e) => setOccurrenceId(e.target.value)}
          disabled={occurrencesQuery.isLoading}
          data-testid="approve-trial-occurrence-select"
        >
          <option value="">
            {occurrencesQuery.isLoading
              ? "Loading occurrences…"
              : occurrences.length === 0
                ? "No occurrences found"
                : "Select an occurrence"}
          </option>
          {occurrences.map((o: AdminSessionOccurrenceView) => (
            <option key={o.occurrence_id} value={o.occurrence_id}>
              {formatAcademyDateTime(o.start_at, null)}
            </option>
          ))}
        </select>
      </label>
      {occurrencesQuery.isError && (
        <p className="text-xs text-red-700">Could not load occurrences for this session.</p>
      )}
      {error && <p role="alert" className="text-sm text-red-700">{error.message}</p>}
      <div className="flex justify-end gap-2 pt-2">
        <Button variant="secondary" size="sm" onClick={onCancel} disabled={pending}>
          Cancel
        </Button>
        <Button
          variant="primary"
          size="sm"
          disabled={pending || !occurrenceId}
          onClick={() => onConfirm(occurrenceId)}
        >
          {pending ? "Approving…" : "Approve"}
        </Button>
      </div>
    </DialogShell>
  );
}

// --- Absences (read-only) ---

function AbsencesTab() {
  const { data, isLoading, isError } = useQuery({
    queryKey: queryKeys.admin.selfServiceAbsences(),
    queryFn: listAdminAbsences,
  });
  const absences = data?.absences ?? [];

  if (isError) return <ErrorState message="Could not load absence notices." />;
  if (isLoading) return <Skeleton />;
  if (absences.length === 0) return <EmptyState message="No absence notices." testId="admin-absences-empty" />;

  return (
    <Card p={20}>
      <div className="overflow-x-auto">
        <table className="w-full min-w-[640px] text-sm">
          <thead>
            <tr className="border-b border-neutral-200 text-left dark:border-neutral-800">
              <Th>Student</Th>
              <Th>Submitted</Th>
              <Th>Notice window</Th>
            </tr>
          </thead>
          <tbody>
            {absences.map((a: AbsenceNoticeAdminRow) => (
              <tr
                key={a.notice_id}
                data-testid={`admin-absences-row-${a.notice_id}`}
                className="border-b border-neutral-100 last:border-0 dark:border-neutral-800"
              >
                <td className="px-2 py-3 font-medium text-rally-base">
                  {a.student_full_name || a.student_id}
                </td>
                <td className="px-2 py-3 text-rally-subtle">{formatAcademyDateTime(a.submitted_at, null)}</td>
                <td className="px-2 py-3">
                  <Chip variant={a.notice_window_met ? "approved" : "pending"} label={a.notice_window_met ? "ON TIME" : "LATE"} />
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </Card>
  );
}

// --- Cancellations (read-only audit) ---

function CancellationsTab() {
  const { data, isLoading, isError } = useQuery({
    queryKey: queryKeys.admin.selfServiceCancellations(),
    queryFn: listAdminCancellations,
  });
  const cancellations = data?.cancellations ?? [];

  if (isError) return <ErrorState message="Could not load cancellations." />;
  if (isLoading) return <Skeleton />;
  if (cancellations.length === 0)
    return <EmptyState message="No self-service cancellations." testId="admin-cancellations-empty" />;

  return (
    <Card p={20}>
      <div className="overflow-x-auto">
        <table className="w-full min-w-[760px] text-sm">
          <thead>
            <tr className="border-b border-neutral-200 text-left dark:border-neutral-800">
              <Th>Student</Th>
              <Th>Session</Th>
              <Th>Cancelled</Th>
              <Th>Fee</Th>
            </tr>
          </thead>
          <tbody>
            {cancellations.map((c: SelfCancellationAdminRow) => {
              const snapshot = c.cancellation_policy_snapshot ?? {};
              const feeBillingError = typeof snapshot.fee_billing_error === "string" ? snapshot.fee_billing_error : null;
              const feeCents = typeof snapshot.cancellation_fee_cents === "number" ? snapshot.cancellation_fee_cents : null;
              return (
                <tr
                  key={c.enrollment_id}
                  data-testid={`admin-cancellations-row-${c.enrollment_id}`}
                  className="border-b border-neutral-100 last:border-0 dark:border-neutral-800"
                >
                  <td className="px-2 py-3 font-medium text-rally-base">
                    {c.student_full_name || c.student_id}
                  </td>
                  <td className="px-2 py-3 text-rally-subtle">{c.session_title || c.session_id}</td>
                  <td className="px-2 py-3 text-rally-subtle">
                    {c.cancelled_at ? formatAcademyDateTime(c.cancelled_at, null) : "—"}
                  </td>
                  <td className="px-2 py-3">
                    <div className="flex items-center gap-2">
                      <span className="text-rally-subtle">
                        {feeCents !== null ? `$${(feeCents / 100).toFixed(2)}` : "—"}
                      </span>
                      {feeBillingError && (
                        <span title={feeBillingError}>
                          <Chip variant="failed" label="FEE BILLING FAILED" />
                        </span>
                      )}
                    </div>
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>
    </Card>
  );
}

// --- Shared ---

function Th({ children, className }: { children: React.ReactNode; className?: string }) {
  return (
    <th className={`px-2 pb-3 font-mono text-[10px] font-bold uppercase tracking-overline text-rally-muted ${className ?? ""}`}>
      {children}
    </th>
  );
}

function DialogShell({
  title,
  onCancel,
  children,
}: {
  title: string;
  onCancel: () => void;
  children: React.ReactNode;
}) {
  return (
    <div
      role="dialog"
      aria-modal="true"
      aria-label={title}
      className="fixed inset-0 z-50 flex items-center justify-center bg-black/40 p-4"
      onClick={onCancel}
    >
      <div
        className="w-full max-w-md space-y-3 rounded-xl bg-white p-5 shadow-xl dark:bg-neutral-900"
        onClick={(e) => e.stopPropagation()}
      >
        <h3 className="text-sm font-bold text-rally-ink">{title}</h3>
        {children}
      </div>
    </div>
  );
}

function DenyDialog({
  title,
  pending,
  error,
  onCancel,
  onConfirm,
}: {
  title: string;
  pending: boolean;
  error: Error | null;
  onCancel: () => void;
  onConfirm: (reason: string) => void;
}) {
  const [reason, setReason] = useState("");
  return (
    <DialogShell title={title} onCancel={onCancel}>
      <label className="block text-xs font-semibold text-rally-muted">
        Reason
        <textarea
          className="mt-1 w-full rounded-lg border px-3 py-2 text-sm"
          style={{ borderColor: "var(--rally-line)" }}
          rows={3}
          value={reason}
          onChange={(e) => setReason(e.target.value)}
          placeholder="Explain why this request is being denied…"
          data-testid="deny-reason-textarea"
        />
      </label>
      {error && <p role="alert" className="text-sm text-red-700">{error.message}</p>}
      <div className="flex justify-end gap-2 pt-2">
        <Button variant="secondary" size="sm" onClick={onCancel} disabled={pending}>
          Cancel
        </Button>
        <Button
          variant="primary"
          size="sm"
          disabled={pending || !reason.trim()}
          onClick={() => onConfirm(reason.trim())}
        >
          {pending ? "Denying…" : "Deny"}
        </Button>
      </div>
    </DialogShell>
  );
}

function Skeleton() {
  return (
    <div className="space-y-2">
      {[0, 1, 2].map((i) => (
        <div key={i} className="h-14 animate-pulse rounded-lg bg-neutral-100 dark:bg-neutral-800" />
      ))}
    </div>
  );
}

function EmptyState({ message, testId }: { message: string; testId: string }) {
  return (
    <p className="text-sm text-rally-subtle" data-testid={testId}>
      {message}
    </p>
  );
}

function ErrorState({ message }: { message: string }) {
  return (
    <p role="alert" className="rounded-md bg-red-50 p-3 text-sm text-red-700">
      {message}
    </p>
  );
}
