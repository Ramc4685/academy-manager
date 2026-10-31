"use client";

/**
 * The five parent-request queues (issue #776).
 *
 * These used to be `app/(admin)/admin/requests/page.tsx`. They now render as
 * tabs inside the single admin Inbox alongside the three admissions queues, so
 * they live here as plain components and the old route is a redirect.
 */

import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { actionCellClass, actionHeaderClass } from "@/lib/sticky-action-column";

import {
  approveMakeup,
  approveTrial,
  denyMakeup,
  denyTrial,
  listAdminAbsences,
  listAdminCancellations,
  listAdminMakeups,
  listAdminSessions,
  listAdminStudents,
  listAdminTrials,
  listSessionOccurrences,
  recordAdminAbsence,
  recordTrialOutcome,
  type AbsenceNoticeAdminRow,
  type AdminSessionOccurrenceView,
  type MakeupRequestAdminRow,
  type SelfCancellationAdminRow,
  type TrialRequestAdminRow,
} from "@/lib/api/admin";
import { queryKeys } from "@/lib/query/keys";
import { formatAcademyDateTime } from "@/lib/format/academy-time";
import { formatPlainDateRange } from "@/lib/format/plain-date";
import { Card } from "@/components/ds/card";
import { Chip, type ChipVariant } from "@/components/ds/chip";
import { Button } from "@/components/ds/button";
import { PhoneList, PhoneListRow } from "@/components/ds/phone-row";
import { useIsPhone } from "@/lib/use-is-phone";
import { Modal } from "@/components/ds/modal";
import { TableSkeleton } from "@/components/ds/skeleton";
import { EmptyState } from "@/components/ds/empty-state";
import { FormField, fieldDescribedBy } from "@/components/ds/form-field";

type StatusFilter = "all" | "pending" | "approved" | "denied" | "expired" | "completed" | "converted";

const MAKEUP_STATUS_FILTERS: StatusFilter[] = ["all", "pending", "approved", "denied", "expired"];
const TRIAL_STATUS_FILTERS: StatusFilter[] = ["all", "pending", "approved", "completed", "denied", "converted"];

/**
 * One dated class, as an admin reads it (issue #841): "U10 Tuesday" over
 * "Thu, Jul 2 · 6:00 PM CDT". Falls back to the occurrence id only when the
 * backend could not resolve it — a deleted class, not the normal path — so a
 * broken join still leaves something to search for rather than a blank cell.
 */
function ClassMoment({
  title,
  startAt,
  fallbackId,
}: {
  title: string | null | undefined;
  startAt: string | null | undefined;
  fallbackId: string | null | undefined;
}) {
  if (!startAt && !title) {
    return <span className="text-rally-subtle">{fallbackId || "—"}</span>;
  }
  return (
    <span className="block">
      {title && <span className="block text-rally-base">{title}</span>}
      {startAt && (
        <span className="block text-rally-subtle">{formatAcademyDateTime(startAt, null)}</span>
      )}
    </span>
  );
}

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
    case "completed":
      return "enrolled";
    default:
      return "pending";
  }
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

export function MakeupsTab() {
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
      void queryClient.invalidateQueries({ queryKey: queryKeys.admin.selfServiceMakeupsAll() });
    },
  });
  const denyMutation = useMutation({
    mutationFn: ({ requestId, reason }: { requestId: string; reason: string }) => denyMakeup(requestId, { reason }),
    onSuccess: () => {
      setDenyTarget(null);
      void queryClient.invalidateQueries({ queryKey: queryKeys.admin.selfServiceMakeupsAll() });
    },
  });

  const makeups = data?.makeups ?? [];

  return (
    <div className="space-y-4">
      <StatusFilterChips value={statusFilter} options={MAKEUP_STATUS_FILTERS} onChange={setStatusFilter} />

      {isError ? (
        <ErrorState message="Could not load makeup requests." />
      ) : isLoading ? (
        <TableSkeleton rows={3} />
      ) : makeups.length === 0 ? (
        <EmptyState title="No makeup requests." data-testid="admin-makeups-empty" compact />
      ) : (
        <MakeupsList makeups={makeups} onDeny={setDenyTarget} onApprove={setApproveTarget} />
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
 * #857: six columns over a 760px minimum, with Approve/Deny in the sticky
 * trailing cell — on a phone the two buttons this queue exists for were off
 * screen. One layout at a time (`lib/use-is-phone.ts`); both reach the same
 * approve/deny dialogs.
 */
function MakeupsList({
  makeups,
  onDeny,
  onApprove,
}: {
  makeups: MakeupRequestAdminRow[];
  onDeny: (row: MakeupRequestAdminRow) => void;
  onApprove: (row: MakeupRequestAdminRow) => void;
}) {
  const isPhone = useIsPhone();
  if (isPhone) {
    return (
      <PhoneList aria-label="Makeup requests" data-testid="admin-makeups-phone-list">
        {makeups.map((m) => {
          const name = m.student_full_name || m.student_id;
          return (
            <PhoneListRow
              key={m.request_id}
              data-testid={`admin-makeups-row-${m.request_id}`}
              title={name}
              primary={<Chip variant={statusChipVariant(m.status)} label={m.status.toUpperCase()} />}
              actionsLabel={`Actions for ${name}`}
              actionsTestId={`admin-makeups-actions-${m.request_id}`}
              actions={
                m.status === "pending"
                  ? [
                      { key: "deny", label: "Deny", onSelect: () => onDeny(m) },
                      { key: "approve", label: "Approve", onSelect: () => onApprove(m) },
                    ]
                  : []
              }
              secondary={
                <>
                  <div>
                    Missed:{" "}
                    <ClassMoment
                      title={m.missed_session_title}
                      startAt={m.missed_start_at}
                      fallbackId={m.missed_occurrence_id}
                    />
                  </div>
                  <div>
                    Target:{" "}
                    {m.approved_target_occurrence_id ? (
                      <ClassMoment
                        title={m.approved_target_session_title}
                        startAt={m.approved_target_start_at}
                        fallbackId={m.approved_target_occurrence_id}
                      />
                    ) : m.requested_target_occurrence_id ? (
                      <ClassMoment
                        title={m.requested_target_session_title}
                        startAt={m.requested_target_start_at}
                        fallbackId={m.requested_target_occurrence_id}
                      />
                    ) : (
                      <span className="text-rally-subtle">No date proposed</span>
                    )}
                  </div>
                  <div>Expires {formatAcademyDateTime(m.expires_at, null)}</div>
                  {m.status === "denied" && m.denial_reason && <div>{m.denial_reason}</div>}
                </>
              }
            />
          );
        })}
      </PhoneList>
    );
  }
  return (
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
                  <Th className={actionHeaderClass}>Actions</Th>
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
                    <td className="px-2 py-3 text-sm">
                      <ClassMoment
                        title={m.missed_session_title}
                        startAt={m.missed_start_at}
                        fallbackId={m.missed_occurrence_id}
                      />
                    </td>
                    <td className="px-2 py-3 text-sm">
                      {m.approved_target_occurrence_id ? (
                        <ClassMoment
                          title={m.approved_target_session_title}
                          startAt={m.approved_target_start_at}
                          fallbackId={m.approved_target_occurrence_id}
                        />
                      ) : m.requested_target_occurrence_id ? (
                        <ClassMoment
                          title={m.requested_target_session_title}
                          startAt={m.requested_target_start_at}
                          fallbackId={m.requested_target_occurrence_id}
                        />
                      ) : (
                        <span className="text-rally-subtle">No date proposed</span>
                      )}
                    </td>
                    <td className="px-2 py-3 text-rally-subtle">{formatAcademyDateTime(m.expires_at, null)}</td>
                    <td className="px-2 py-3">
                      <Chip variant={statusChipVariant(m.status)} label={m.status.toUpperCase()} />
                      {m.status === "denied" && m.denial_reason && (
                        <p className="mt-1 text-xs text-rally-subtle">{m.denial_reason}</p>
                      )}
                    </td>
                    <td className={`${actionCellClass} bg-white`}>
                      {m.status === "pending" ? (
                        <div className="flex justify-end gap-2">
                          <Button variant="secondary" size="sm" onClick={() => onDeny(m)}>
                            Deny
                          </Button>
                          <Button variant="primary" size="sm" onClick={() => onApprove(m)}>
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
  );
}

/**
 * Approve dialog for makeups (issue #841).
 *
 * This used to ask the admin to paste an occurrence id copied from another
 * screen. The list read now resolves the session behind each occurrence, so
 * the dialog can offer the same real picker the trials dialog uses: the class
 * dates of the makeup's own session, by date.
 *
 * The session it picks from is the one the parent proposed a target in, or —
 * when they proposed nothing — the session they missed, which is where a
 * makeup normally lands.
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
  const sessionId =
    request.approved_target_session_id ??
    request.requested_target_session_id ??
    request.missed_session_id ??
    "";
  const [occurrenceId, setOccurrenceId] = useState(request.requested_target_occurrence_id ?? "");
  const occurrencesQuery = useQuery({
    queryKey: queryKeys.admin.sessionOccurrences(sessionId),
    queryFn: () => listSessionOccurrences(sessionId),
    enabled: sessionId !== "",
  });
  const occurrences = (occurrencesQuery.data?.occurrences ?? []).filter(
    (o: AdminSessionOccurrenceView) => o.status !== "cancelled",
  );

  return (
    <DialogShell title="Approve makeup request" onCancel={onCancel}>
      <p className="text-sm text-rally-subtle">
        {request.student_full_name || request.student_id} missed{" "}
        {request.missed_session_title ?? "a class"}
        {request.missed_start_at ? ` on ${formatAcademyDateTime(request.missed_start_at, null)}` : ""}.
      </p>
      <label className="block text-xs font-semibold text-rally-muted">
        Class date to attend instead
        <select
          className="mt-1 min-h-touch w-full rounded-lg border px-3 text-sm"
          style={{ borderColor: "var(--rally-line)" }}
          value={occurrenceId}
          onChange={(e) => setOccurrenceId(e.target.value)}
          disabled={sessionId === "" || occurrencesQuery.isLoading}
          data-testid="approve-makeup-occurrence-select"
        >
          <option value="">
            {sessionId === ""
              ? "No class found for this request"
              : occurrencesQuery.isLoading
                ? "Loading dates…"
                : occurrences.length === 0
                  ? "No dates found"
                  : "Select a date"}
          </option>
          {occurrences.map((o: AdminSessionOccurrenceView) => (
            <option key={o.occurrence_id} value={o.occurrence_id}>
              {formatAcademyDateTime(o.start_at, null)}
            </option>
          ))}
        </select>
      </label>
      {occurrencesQuery.isError && (
        <p className="text-xs text-red-700">Could not load the class dates for this request.</p>
      )}
      {/* #860: the pause and registration dialogs say what the family is told,
          so this one must too — and the honest answer today is "nothing is
          sent". `ApproveMakeupRequest` takes no notifier (it is billing- and
          notification-free by design), so the decision only shows up when the
          parent next opens their account. An admin who assumes an email went
          out would never follow up. */}
      <p className="text-xs text-rally-muted" data-testid="approve-makeup-notice">
        No email is sent. The family sees the new date in their parent account.
      </p>
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

// --- Trials ---

export function TrialsTab() {
  const queryClient = useQueryClient();
  const [statusFilter, setStatusFilter] = useState<StatusFilter>("pending");
  const [denyTarget, setDenyTarget] = useState<TrialRequestAdminRow | null>(null);
  const [approveTarget, setApproveTarget] = useState<TrialRequestAdminRow | null>(null);
  const [noShowTarget, setNoShowTarget] = useState<TrialRequestAdminRow | null>(null);

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
      void queryClient.invalidateQueries({ queryKey: queryKeys.admin.selfServiceTrialsAll() });
    },
  });
  const denyMutation = useMutation({
    mutationFn: ({ requestId, reason }: { requestId: string; reason: string }) => denyTrial(requestId, { reason }),
    onSuccess: () => {
      setDenyTarget(null);
      void queryClient.invalidateQueries({ queryKey: queryKeys.admin.selfServiceTrialsAll() });
    },
  });

  // People CRM L3a: Came / Didn't come on an approved (or completed) trial.
  const outcomeMutation = useMutation({
    mutationFn: ({ requestId, outcome }: { requestId: string; outcome: "came" | "no_show" }) =>
      recordTrialOutcome(requestId, outcome),
    onSuccess: () => {
      setNoShowTarget(null);
      void queryClient.invalidateQueries({ queryKey: queryKeys.admin.selfServiceTrialsAll() });
    },
  });

  const trials = data?.trials ?? [];

  return (
    <div className="space-y-4">
      <StatusFilterChips value={statusFilter} options={TRIAL_STATUS_FILTERS} onChange={setStatusFilter} />

      {isError ? (
        <ErrorState message="Could not load trial requests." />
      ) : isLoading ? (
        <TableSkeleton rows={3} />
      ) : trials.length === 0 ? (
        <EmptyState title="No trial requests." data-testid="admin-trials-empty" compact />
      ) : (
        <TrialsList
          trials={trials}
          onDeny={setDenyTarget}
          onApprove={setApproveTarget}
          onCame={(row) => outcomeMutation.mutate({ requestId: row.request_id, outcome: "came" })}
          onNoShow={setNoShowTarget}
          outcomePendingId={outcomeMutation.isPending ? outcomeMutation.variables?.requestId ?? null : null}
          outcomeError={
            outcomeMutation.isError && !noShowTarget
              ? { requestId: outcomeMutation.variables?.requestId ?? "", message: outcomeErrorText(outcomeMutation.error) }
              : null
          }
        />
      )}

      {noShowTarget && (
        <NoShowDialog
          name={trialChildName(noShowTarget)}
          pending={outcomeMutation.isPending}
          error={outcomeMutation.isError ? outcomeErrorText(outcomeMutation.error) : null}
          onCancel={() => {
            setNoShowTarget(null);
            outcomeMutation.reset();
          }}
          onConfirm={() => outcomeMutation.mutate({ requestId: noShowTarget.request_id, outcome: "no_show" })}
        />
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

function trialChildName(t: TrialRequestAdminRow): string {
  return t.prospective_child_name || t.student_full_name || "Existing child";
}

/** People CRM L3a: a trial takes Came / Didn't come once approved (and may be corrected). */
function canRecordOutcome(t: TrialRequestAdminRow): boolean {
  return (t.status === "approved" || t.status === "completed") && Boolean(t.assigned_occurrence_id);
}

function outcomeLabel(outcome: TrialRequestAdminRow["outcome"]): string | null {
  if (outcome === "came") return "CAME";
  if (outcome === "no_show") return "DIDN'T COME";
  return null;
}

function outcomeErrorText(err: unknown): string {
  const status = (err as { status?: number } | null)?.status;
  if (status === 409) return "This trial can't take an outcome yet (not started, cancelled, or already converted).";
  return "Could not save the trial outcome. Try again.";
}

/** #857, same shape as the makeups queue. */
function TrialsList({
  trials,
  onDeny,
  onApprove,
  onCame,
  onNoShow,
  outcomePendingId,
  outcomeError,
}: {
  trials: TrialRequestAdminRow[];
  onDeny: (row: TrialRequestAdminRow) => void;
  onApprove: (row: TrialRequestAdminRow) => void;
  onCame: (row: TrialRequestAdminRow) => void;
  onNoShow: (row: TrialRequestAdminRow) => void;
  outcomePendingId: string | null;
  outcomeError: { requestId: string; message: string } | null;
}) {
  const isPhone = useIsPhone();
  if (isPhone) {
    return (
      <PhoneList aria-label="Trial requests" data-testid="admin-trials-phone-list">
        {trials.map((t) => {
          const name = t.prospective_child_name || t.student_full_name || "Existing child";
          return (
            <PhoneListRow
              key={t.request_id}
              data-testid={`admin-trials-row-${t.request_id}`}
              title={name}
              primary={<Chip variant={statusChipVariant(t.status)} label={t.status.toUpperCase()} />}
              actionsLabel={`Actions for ${name}`}
              actionsTestId={`admin-trials-actions-${t.request_id}`}
              actions={
                t.status === "pending"
                  ? [
                      { key: "deny", label: "Deny", onSelect: () => onDeny(t) },
                      { key: "approve", label: "Approve", onSelect: () => onApprove(t) },
                    ]
                  : canRecordOutcome(t)
                    ? [
                        ...(t.outcome !== "came"
                          ? [{ key: "came", label: "Came", onSelect: () => onCame(t) }]
                          : []),
                        ...(t.outcome !== "no_show"
                          ? [{ key: "no_show", label: "Didn't come", onSelect: () => onNoShow(t) }]
                          : []),
                      ]
                    : []
              }
              secondary={
                <>
                  <div className="break-words">
                    {t.requested_session_title || t.requested_session_id}
                  </div>
                  <div>
                    Preferred {formatPlainDateRange(t.preferred_start, t.preferred_end)}
                  </div>
                  <div>
                    {t.assigned_occurrence_start_at
                      ? `Assigned ${formatAcademyDateTime(t.assigned_occurrence_start_at, null)}`
                      : t.assigned_occurrence_id
                        ? `Assigned ${t.assigned_occurrence_id}`
                        : "Not scheduled"}
                  </div>
                  {t.status === "denied" && t.denial_reason && <div>{t.denial_reason}</div>}
                  {outcomeLabel(t.outcome) && <div>{outcomeLabel(t.outcome)}</div>}
                  {outcomeError?.requestId === t.request_id && (
                    <div role="alert" className="text-red-700">{outcomeError.message}</div>
                  )}
                </>
              }
            />
          );
        })}
      </PhoneList>
    );
  }
  return (
    <Card p={20}>
          <div className="overflow-x-auto">
            <table className="w-full min-w-[760px] text-sm">
              <thead>
                <tr className="border-b border-neutral-200 text-left dark:border-neutral-800">
                  <Th>Student</Th>
                  <Th>Class</Th>
                  <Th>Preferred window</Th>
                  <Th>Assigned date</Th>
                  <Th>Status</Th>
                  <Th className={actionHeaderClass}>Actions</Th>
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
                      {t.prospective_child_name || t.student_full_name || "Existing child"}
                    </td>
                    <td className="px-2 py-3 text-rally-subtle">
                      {t.requested_session_title || t.requested_session_id}
                    </td>
                    <td className="px-2 py-3 text-rally-subtle">
                      {formatPlainDateRange(t.preferred_start, t.preferred_end)}
                    </td>
                    <td className="px-2 py-3 text-rally-subtle">
                      {t.assigned_occurrence_start_at
                        ? formatAcademyDateTime(t.assigned_occurrence_start_at, null)
                        : t.assigned_occurrence_id
                          ? t.assigned_occurrence_id
                          : "Not scheduled"}
                    </td>
                    <td className="px-2 py-3">
                      <Chip variant={statusChipVariant(t.status)} label={t.status.toUpperCase()} />
                      {t.status === "denied" && t.denial_reason && (
                        <p className="mt-1 text-xs text-rally-subtle">{t.denial_reason}</p>
                      )}
                      {outcomeLabel(t.outcome) && (
                        <p className="mt-1 text-xs font-semibold text-rally-base" data-testid={`admin-trials-outcome-${t.request_id}`}>
                          {outcomeLabel(t.outcome)}
                        </p>
                      )}
                      {outcomeError?.requestId === t.request_id && (
                        <p role="alert" className="mt-1 text-xs text-red-700">{outcomeError.message}</p>
                      )}
                    </td>
                    <td className={`${actionCellClass} bg-white`}>
                      {t.status === "pending" ? (
                        <div className="flex justify-end gap-2">
                          <Button variant="secondary" size="sm" onClick={() => onDeny(t)}>
                            Deny
                          </Button>
                          <Button variant="primary" size="sm" onClick={() => onApprove(t)}>
                            Approve
                          </Button>
                        </div>
                      ) : canRecordOutcome(t) ? (
                        <div className="flex justify-end gap-2" role="group" aria-label={`Trial outcome for ${trialChildName(t)}`}>
                          <Button
                            variant="secondary"
                            size="sm"
                            data-testid={`admin-trials-came-${t.request_id}`}
                            aria-pressed={t.outcome === "came"}
                            disabled={outcomePendingId === t.request_id || t.outcome === "came"}
                            onClick={() => onCame(t)}
                          >
                            Came
                          </Button>
                          <Button
                            variant="secondary"
                            size="sm"
                            data-testid={`admin-trials-no-show-${t.request_id}`}
                            aria-pressed={t.outcome === "no_show"}
                            disabled={outcomePendingId === t.request_id || t.outcome === "no_show"}
                            onClick={() => onNoShow(t)}
                          >
                            Didn&apos;t come
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
        {request.prospective_child_name || request.student_full_name || "Existing child"} ·{" "}
        {request.requested_session_title || request.requested_session_id} · preferred{" "}
        {formatPlainDateRange(request.preferred_start, request.preferred_end)}
      </p>
      <label className="block text-xs font-semibold text-rally-muted">
        Class date
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
              ? "Loading dates…"
              : occurrences.length === 0
                ? "No dates found"
                : "Select a date"}
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
      {/* #860, same as the makeup dialog: `ApproveTrialRequest` has no
          notifier either, so say so rather than let the admin assume. */}
      <p className="text-xs text-rally-muted" data-testid="approve-trial-notice">
        No email is sent. The family sees the trial date in their parent account.
      </p>
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

// --- Absences ---

export function AbsencesTab() {
  const queryClient = useQueryClient();
  const [recording, setRecording] = useState(false);
  const { data, isLoading, isError } = useQuery({
    queryKey: queryKeys.admin.selfServiceAbsences(),
    queryFn: listAdminAbsences,
  });
  const absences = data?.absences ?? [];

  const recordMutation = useMutation({
    mutationFn: recordAdminAbsence,
    onSuccess: () => {
      setRecording(false);
      void queryClient.invalidateQueries({ queryKey: queryKeys.admin.selfServiceAbsences() });
    },
  });

  const dialog = recording ? (
    <RecordAbsenceDialog
      pending={recordMutation.isPending}
      error={recordMutation.isError ? recordMutation.error : null}
      onCancel={() => {
        recordMutation.reset();
        setRecording(false);
      }}
      onConfirm={(payload) => recordMutation.mutate(payload)}
    />
  ) : null;

  const toolbar = (
    <div className="flex justify-end">
      <Button
        variant="primary"
        size="sm"
        onClick={() => setRecording(true)}
        data-testid="admin-absences-record"
      >
        Record absence
      </Button>
    </div>
  );

  if (isError) {
    return (
      <div className="space-y-4">
        {toolbar}
        <ErrorState message="Could not load absence notices." />
        {dialog}
      </div>
    );
  }
  if (isLoading) {
    return (
      <div className="space-y-4">
        {toolbar}
        <TableSkeleton rows={3} />
      </div>
    );
  }

  return (
    <div className="space-y-4">
      {toolbar}
      {absences.length === 0 ? (
        <EmptyState title="No absence notices." data-testid="admin-absences-empty" compact />
      ) : (
        <AbsencesList absences={absences} />
      )}
      {dialog}
    </div>
  );
}

/** #857: a four-column 640px table on a 400px screen. Read-only, so no menu. */
function AbsencesList({ absences }: { absences: AbsenceNoticeAdminRow[] }) {
  const isPhone = useIsPhone();
  if (isPhone) {
    return (
      <PhoneList aria-label="Absence notices" data-testid="admin-absences-phone-list">
        {absences.map((a) => (
          <PhoneListRow
            key={a.notice_id}
            data-testid={`admin-absences-row-${a.notice_id}`}
            title={a.student_full_name || a.student_id}
            primary={
              <Chip
                variant={a.notice_window_met ? "approved" : "pending"}
                label={a.notice_window_met ? "ON TIME" : "LATE"}
              />
            }
            secondary={
              <>
                <div>
                  Missing:{" "}
                  <ClassMoment
                    title={a.occurrence_session_title}
                    startAt={a.occurrence_start_at}
                    fallbackId="Class unavailable"
                  />
                </div>
                <div>Submitted {formatAcademyDateTime(a.submitted_at, null)}</div>
                <div>{a.recorded_by_admin ? "Recorded by admin" : "Parent"}</div>
              </>
            }
          />
        ))}
      </PhoneList>
    );
  }
  return (
    <Card p={20}>
          <div className="overflow-x-auto">
            <table className="w-full min-w-[760px] text-sm">
              <thead>
                <tr className="border-b border-neutral-200 text-left dark:border-neutral-800">
                  <Th>Student</Th>
                  <Th>Class missed</Th>
                  <Th>Submitted</Th>
                  <Th>Source</Th>
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
                    <td className="px-2 py-3">
                      <ClassMoment
                        title={a.occurrence_session_title}
                        startAt={a.occurrence_start_at}
                        fallbackId="Class unavailable"
                      />
                    </td>
                    <td className="px-2 py-3 text-rally-subtle">{formatAcademyDateTime(a.submitted_at, null)}</td>
                    <td className="px-2 py-3 text-rally-subtle">
                      {a.recorded_by_admin ? "Recorded by admin" : "Parent"}
                    </td>
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

/**
 * Record an absence notice on a parent's behalf (#616). Reuses the admin
 * students list for the student picker, the upcoming-sessions list (same
 * one the transfer dialog uses) for the class, and the session's dated
 * occurrences for the date — past dates are allowed, which is the point.
 */
function RecordAbsenceDialog({
  pending,
  error,
  onCancel,
  onConfirm,
}: {
  pending: boolean;
  error: Error | null;
  onCancel: () => void;
  onConfirm: (payload: { student_id: string; occurrence_id: string; counts_toward_makeup: boolean }) => void;
}) {
  const [studentId, setStudentId] = useState("");
  const [sessionId, setSessionId] = useState("");
  const [occurrenceId, setOccurrenceId] = useState("");
  const [countsTowardMakeup, setCountsTowardMakeup] = useState(true);

  const studentsQuery = useQuery({
    queryKey: queryKeys.admin.students(),
    queryFn: listAdminStudents,
  });
  const sessionsQuery = useQuery({
    queryKey: queryKeys.admin.sessions("upcoming"),
    queryFn: () => listAdminSessions(undefined, { window: "upcoming" }),
  });
  const occurrencesQuery = useQuery({
    queryKey: queryKeys.admin.sessionOccurrences(sessionId),
    queryFn: () => listSessionOccurrences(sessionId),
    enabled: sessionId !== "",
  });

  const students = studentsQuery.data?.students ?? [];
  const sessions = sessionsQuery.data?.sessions ?? [];
  // Newest first: an admin recording a phone call is usually looking for a
  // date that has just passed.
  const occurrences = [...(occurrencesQuery.data?.occurrences ?? [])].sort((a, b) =>
    b.start_at.localeCompare(a.start_at),
  );

  const selectClass = "mt-1 min-h-touch w-full rounded-lg border border-rally-line px-3 text-sm";

  return (
    <DialogShell title="Record absence" onCancel={onCancel}>
      <p className="text-sm text-rally-subtle">
        For a parent who called or messaged instead of using the portal. Past class dates are
        allowed. No email is sent.
      </p>
      <label className="block text-xs font-semibold text-rally-muted">
        Student
        <select
          className={selectClass}
          value={studentId}
          onChange={(e) => setStudentId(e.target.value)}
          disabled={studentsQuery.isLoading}
          data-testid="record-absence-student-select"
        >
          <option value="">
            {studentsQuery.isLoading
              ? "Loading students…"
              : students.length === 0
                ? "No students found"
                : "Select a student"}
          </option>
          {students.map((s) => (
            <option key={s.student_id} value={s.student_id}>
              {s.full_name}
            </option>
          ))}
        </select>
      </label>
      <label className="block text-xs font-semibold text-rally-muted">
        Class
        <select
          className={selectClass}
          value={sessionId}
          onChange={(e) => {
            setSessionId(e.target.value);
            setOccurrenceId("");
          }}
          disabled={sessionsQuery.isLoading}
          data-testid="record-absence-session-select"
        >
          <option value="">
            {sessionsQuery.isLoading
              ? "Loading classes…"
              : sessions.length === 0
                ? "No classes found"
                : "Select a class"}
          </option>
          {sessions.map((s) => (
            <option key={s.session_id} value={s.session_id}>
              {s.title}
            </option>
          ))}
        </select>
      </label>
      <label className="block text-xs font-semibold text-rally-muted">
        Class date
        <select
          className={selectClass}
          value={occurrenceId}
          onChange={(e) => setOccurrenceId(e.target.value)}
          disabled={sessionId === "" || occurrencesQuery.isLoading}
          data-testid="record-absence-occurrence-select"
        >
          <option value="">
            {sessionId === ""
              ? "Select a class first"
              : occurrencesQuery.isLoading
                ? "Loading dates…"
                : occurrences.length === 0
                  ? "No dates found"
                  : "Select a date"}
          </option>
          {occurrences.map((o: AdminSessionOccurrenceView) => (
            <option key={o.occurrence_id} value={o.occurrence_id}>
              {formatAcademyDateTime(o.start_at, null)}
              {o.status === "cancelled" ? " (cancelled)" : ""}
            </option>
          ))}
        </select>
      </label>
      <label className="flex items-center gap-2 text-sm text-rally-base">
        <input
          type="checkbox"
          checked={countsTowardMakeup}
          onChange={(e) => setCountsTowardMakeup(e.target.checked)}
          data-testid="record-absence-counts-toward-makeup"
        />
        Counts toward a make-up
      </label>
      {(studentsQuery.isError || sessionsQuery.isError || occurrencesQuery.isError) && (
        <p className="text-xs text-red-700">Could not load the pickers; try again.</p>
      )}
      {error && <p role="alert" className="text-sm text-red-700">{error.message}</p>}
      <div className="flex justify-end gap-2 pt-2">
        <Button variant="secondary" size="sm" onClick={onCancel} disabled={pending}>
          Cancel
        </Button>
        <Button
          variant="primary"
          size="sm"
          disabled={pending || !studentId || !occurrenceId}
          onClick={() =>
            onConfirm({ student_id: studentId, occurrence_id: occurrenceId, counts_toward_makeup: countsTowardMakeup })
          }
          data-testid="record-absence-submit"
        >
          {pending ? "Recording…" : "Record"}
        </Button>
      </div>
    </DialogShell>
  );
}

// --- Cancellations (read-only audit) ---

/**
 * The cancellation fee is line 1's primary slot (#857): on a phone it was the
 * fourth column of a 760px table, and it is the one number an admin is here
 * for. Read from the same policy snapshot the table reads.
 */
function cancellationFee(c: SelfCancellationAdminRow): {
  label: string;
  billingError: string | null;
} {
  const snapshot = c.cancellation_policy_snapshot ?? {};
  const feeBillingError =
    typeof snapshot.fee_billing_error === "string" ? snapshot.fee_billing_error : null;
  const feeCents =
    typeof snapshot.cancellation_fee_cents === "number" ? snapshot.cancellation_fee_cents : null;
  return {
    label: feeCents !== null ? `$${(feeCents / 100).toFixed(2)}` : "—",
    billingError: feeBillingError,
  };
}

export function CancellationsTab() {
  const isPhone = useIsPhone();
  const { data, isLoading, isError } = useQuery({
    queryKey: queryKeys.admin.selfServiceCancellations(),
    queryFn: listAdminCancellations,
  });
  const cancellations = data?.cancellations ?? [];

  if (isError) return <ErrorState message="Could not load cancellations." />;
  if (isLoading) return <TableSkeleton rows={3} />;
  if (cancellations.length === 0)
    return <EmptyState title="No self-service cancellations." data-testid="admin-cancellations-empty" compact />;

  if (isPhone) {
    return (
      <PhoneList aria-label="Cancellations" data-testid="admin-cancellations-phone-list">
        {cancellations.map((c: SelfCancellationAdminRow) => {
          const fee = cancellationFee(c);
          return (
            <PhoneListRow
              key={c.enrollment_id}
              data-testid={`admin-cancellations-row-${c.enrollment_id}`}
              title={c.student_full_name || c.student_id}
              primary={
                <span className="font-mono text-sm font-semibold tabular-nums text-rally-base">
                  {fee.label}
                </span>
              }
              secondary={
                <>
                  <div className="break-words">{c.session_title || c.session_id}</div>
                  <div>
                    Cancelled{" "}
                    {c.cancelled_at ? formatAcademyDateTime(c.cancelled_at, null) : "—"}
                  </div>
                  {fee.billingError && (
                    <div title={fee.billingError}>
                      <Chip variant="failed" label="FEE BILLING FAILED" />
                    </div>
                  )}
                </>
              }
            />
          );
        })}
      </PhoneList>
    );
  }

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
              const fee = cancellationFee(c);
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
                      <span className="text-rally-subtle">{fee.label}</span>
                      {fee.billingError && (
                        <span title={fee.billingError}>
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
    <Modal open onClose={onCancel} title={title}>
      {children}
    </Modal>
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
      <FormField label="Reason" htmlFor="deny-reason" error={error?.message}>
        <textarea
          id="deny-reason"
          aria-describedby={fieldDescribedBy("deny-reason", { error: error?.message })}
          aria-invalid={error ? true : undefined}
          className="mt-1 w-full rounded-lg border border-rally-line px-3 py-2 text-sm"
          rows={3}
          value={reason}
          onChange={(e) => setReason(e.target.value)}
          placeholder="Explain why this request is being denied…"
          data-testid="deny-reason-textarea"
        />
      </FormField>
      {/* #860: both callers are makeup/trial denials, neither of which
          notifies. The reason is stored and shown in the parent's account. */}
      <p className="text-xs text-rally-muted" data-testid="deny-notice">
        No email is sent. The family sees this reason in their parent account.
      </p>
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

/** People CRM L3a: "Didn't come" is confirmed before it is saved. */
function NoShowDialog({
  name,
  pending,
  error,
  onCancel,
  onConfirm,
}: {
  name: string;
  pending: boolean;
  error: string | null;
  onCancel: () => void;
  onConfirm: () => void;
}) {
  return (
    <DialogShell title="Mark trial as didn't come" onCancel={onCancel}>
      <p className="text-sm text-rally-base" data-testid="no-show-confirm-text">
        Record that {name} didn&apos;t come to the trial? The trial closes as completed. No email
        is sent.
      </p>
      {error && (
        <p role="alert" className="text-xs text-red-700">
          {error}
        </p>
      )}
      <div className="flex justify-end gap-2 pt-2">
        <Button variant="secondary" size="sm" onClick={onCancel} disabled={pending}>
          Cancel
        </Button>
        <Button
          variant="primary"
          size="sm"
          data-testid="no-show-confirm"
          disabled={pending}
          onClick={onConfirm}
        >
          {pending ? "Saving…" : "Didn't come"}
        </Button>
      </div>
    </DialogShell>
  );
}

function ErrorState({ message }: { message: string }) {
  return (
    <p role="alert" className="rounded-md bg-red-50 p-3 text-sm text-red-700">
      {message}
    </p>
  );
}
