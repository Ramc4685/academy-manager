"use client";

import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import {
  approvePauseRequest,
  declinePauseRequest,
  listAdminPauseRequests,
  type AdminPauseRequestView,
} from "@/lib/api/admin";
import { Card } from "@/components/ds/card";
import { Chip, type ChipVariant } from "@/components/ds/chip";
import { Button } from "@/components/ds/button";
import { ConfirmActionDialog } from "@/components/admin/confirm-action-dialog";
import { PhoneList, PhoneListRow } from "@/components/ds/phone-row";
import { useIsPhone } from "@/lib/use-is-phone";
import { actionCellClass, actionHeaderClass } from "@/lib/sticky-action-column";

/** #838: approving or declining a pause is one click away from the family's bill. */
type PauseDecision = { request: AdminPauseRequestView; decision: "approve" | "decline" };

export function PausesTab() {
  const queryClient = useQueryClient();
  const [confirming, setConfirming] = useState<PauseDecision | null>(null);
  const { data, isLoading, isError } = useQuery({
    queryKey: ["admin", "pause-requests"],
    queryFn: listAdminPauseRequests,
  });
  const approveMutation = useMutation({
    mutationFn: approvePauseRequest,
    onSuccess: () => void queryClient.invalidateQueries({ queryKey: ["admin", "pause-requests"] }),
  });
  const declineMutation = useMutation({
    mutationFn: declinePauseRequest,
    onSuccess: () => void queryClient.invalidateQueries({ queryKey: ["admin", "pause-requests"] }),
  });

  const requests = data?.requests ?? [];

  return (
    <div data-testid="admin-pause-requests" className="space-y-4">
      {isError ? (
        <p role="alert" className="rounded-md bg-red-50 p-3 text-sm text-red-700">
          Could not load pause requests.
        </p>
      ) : isLoading ? (
        <Skeleton />
      ) : requests.length === 0 ? (
        <p className="text-sm text-rally-subtle" data-testid="admin-pause-requests-empty">
          No pending pause requests.
        </p>
      ) : (
        <PausesList
          requests={requests}
          disabled={approveMutation.isPending || declineMutation.isPending}
          onApprove={(request) => setConfirming({ request, decision: "approve" })}
          onDecline={(request) => setConfirming({ request, decision: "decline" })}
        />
      )}

      {confirming && (
        <ConfirmActionDialog
          open
          onOpenChange={(open) => !open && setConfirming(null)}
          overline={confirming.decision === "approve" ? "Approve pause" : "Decline pause"}
          title={
            confirming.decision === "approve"
              ? "Approve this pause request?"
              : "Decline this pause request?"
          }
          subject={`${confirming.request.student_name || confirming.request.student_id || "Student"} · ${
            confirming.request.session_title || confirming.request.session_id || "session pending"
          } · ${pauseLabel(confirming.request)}`}
          consequence={
            confirming.decision === "approve" ? (
              <>
                <p>
                  The seat is released for the pause, so the student stops attending.{" "}
                  {billingImpactLabel(confirming.request)}.
                </p>
                <p>
                  {confirming.request.parent_name ||
                    confirming.request.parent_email ||
                    "The family"}{" "}
                  is emailed that the pause was approved.
                </p>
              </>
            ) : (
              <>
                <p>
                  Nothing changes: the seat stays, attendance continues and the family keeps being
                  invoiced as usual.
                </p>
                <p>
                  {confirming.request.parent_name ||
                    confirming.request.parent_email ||
                    "The family"}{" "}
                  is emailed that the request was declined.
                </p>
              </>
            )
          }
          confirmLabel={confirming.decision === "approve" ? "Approve pause" : "Decline pause"}
          confirmVariant={confirming.decision === "approve" ? "primary" : "danger"}
          pending={approveMutation.isPending || declineMutation.isPending}
          onConfirm={() => {
            if (confirming.decision === "approve") {
              approveMutation.mutate(confirming.request.pause_request_id);
            } else {
              declineMutation.mutate(confirming.request.pause_request_id);
            }
            setConfirming(null);
          }}
        />
      )}
    </div>
  );
}

/**
 * #860: on a phone the sticky Decline/Approve cell sat on top of the session,
 * the pause dates and the reason — the admin was deciding blind. The shared
 * phone row (#847) puts every one of those facts above a 44px actions menu, so
 * the decision is made from what the family actually asked for.
 *
 * Both layouts call the same `onApprove`/`onDecline` the table already used:
 * one confirm dialog, one derivation of the labels, two layouts.
 */
function PausesList({
  requests,
  disabled,
  onApprove,
  onDecline,
}: {
  requests: AdminPauseRequestView[];
  disabled: boolean;
  onApprove: (request: AdminPauseRequestView) => void;
  onDecline: (request: AdminPauseRequestView) => void;
}) {
  const isPhone = useIsPhone();
  if (isPhone) {
    return (
      <Card p={0}>
        <PhoneList aria-label="Pause requests" data-testid="admin-pause-requests-phone-list">
          {requests.map((request) => {
            const who = request.parent_name || request.parent_email || "Parent";
            return (
              <PhoneListRow
                key={request.pause_request_id}
                data-testid={`admin-pause-requests-row-${request.pause_request_id}`}
                title={who}
                primary={
                  <Chip variant={mapStatus(request.status)} label={request.status.toUpperCase()} />
                }
                actionsLabel={`Actions for ${who}`}
                actionsTestId={`admin-pause-requests-actions-${request.pause_request_id}`}
                actions={
                  request.status === "pending" && !disabled
                    ? [
                        { key: "decline", label: "Decline", onSelect: () => onDecline(request) },
                        { key: "approve", label: "Approve", onSelect: () => onApprove(request) },
                      ]
                    : []
                }
                secondary={
                  <>
                    <div>Student: {request.student_name || request.student_id || "Unknown"}</div>
                    <div className="text-rally-base">
                      {request.session_title || request.session_id || "Session pending"}
                    </div>
                    <div>{sessionDetail(request)}</div>
                    <div className="text-rally-base">{pauseLabel(request)}</div>
                    <div>{billingImpactLabel(request)}</div>
                    <div>Requested {formatDateTime(request.created_at)}</div>
                    <div>{request.reason || "No reason given"}</div>
                  </>
                }
              />
            );
          })}
        </PhoneList>
      </Card>
    );
  }
  return (
    <Card p={20}>
          <div className="overflow-x-auto">
            <table className="w-full min-w-[840px] text-sm">
              <thead>
                <tr className="border-b border-neutral-200 text-left dark:border-neutral-800">
                  <th className="px-2 pb-3 font-mono text-[10px] font-bold uppercase tracking-overline text-rally-muted">Who</th>
                  <th className="px-2 pb-3 font-mono text-[10px] font-bold uppercase tracking-overline text-rally-muted">Session</th>
                  <th className="px-2 pb-3 font-mono text-[10px] font-bold uppercase tracking-overline text-rally-muted">Pause</th>
                  <th className="px-2 pb-3 font-mono text-[10px] font-bold uppercase tracking-overline text-rally-muted">Reason</th>
                  <th className="px-2 pb-3 font-mono text-[10px] font-bold uppercase tracking-overline text-rally-muted">Status</th>
                  <th className={`px-2 pb-3 font-mono text-[10px] font-bold uppercase tracking-overline text-rally-muted ${actionHeaderClass}`}>Actions</th>
                </tr>
              </thead>
              <tbody>
                {requests.map((request) => (
                  <PauseRow
                    key={request.pause_request_id}
                    request={request}
                    disabled={disabled}
                    onApprove={() => onApprove(request)}
                    onDecline={() => onDecline(request)}
                  />
                ))}
              </tbody>
            </table>
          </div>
        </Card>
  );
}

function mapStatus(status: string): ChipVariant {
  if (status === "approved") return "approved";
  if (status === "declined") return "failed";
  return "pending";
}

function PauseRow({
  request,
  disabled,
  onApprove,
  onDecline,
}: {
  request: AdminPauseRequestView;
  disabled: boolean;
  onApprove: () => void;
  onDecline: () => void;
}) {
  const isPending = request.status === "pending";
  return (
    <tr data-testid={`admin-pause-requests-row-${request.pause_request_id}`} className="border-b border-neutral-100 last:border-0 dark:border-neutral-800">
      <td className="px-2 py-3">
        <div className="font-medium text-rally-base">{request.parent_name || request.parent_email || request.parent_id}</div>
        <div className="mt-1 text-xs text-rally-subtle">
          Student: {request.student_name || request.student_id || "Unknown"}
        </div>
      </td>
      <td className="px-2 py-3">
        <div className="font-medium text-rally-base">{request.session_title || request.session_id || "Session pending"}</div>
        <div className="mt-1 text-xs text-rally-subtle">
          {sessionDetail(request)}
        </div>
      </td>
      <td className="px-2 py-3">
        <div className="font-medium text-rally-base">{pauseLabel(request)}</div>
        <div className="mt-1 text-xs text-rally-subtle">{billingImpactLabel(request)}</div>
        <div className="mt-1 text-xs text-rally-subtle">Requested {formatDateTime(request.created_at)}</div>
      </td>
      <td className="px-2 py-3 text-rally-subtle">{request.reason || "—"}</td>
      <td className="px-2 py-3">
        <Chip variant={mapStatus(request.status)} label={request.status.toUpperCase()} />
      </td>
      <td className={`${actionCellClass} bg-white`}>
        {isPending ? (
          <div className="flex justify-end gap-2">
            <Button
              variant="secondary"
              size="sm"
              onClick={onDecline}
              disabled={disabled}
            >
              Decline
            </Button>
            <Button
              variant="primary"
              size="sm"
              onClick={onApprove}
              disabled={disabled}
            >
              Approve
            </Button>
          </div>
        ) : null}
      </td>
    </tr>
  );
}

function pauseLabel(request: AdminPauseRequestView): string {
  if (request.pause_kind === "indefinite") {
    return request.review_on ? `Review ${formatDate(request.review_on)}` : "Review date missing";
  }
  if (!request.resume_on) return request.period || "Resume date pending";
  return `Resume ${formatDate(request.resume_on)}`;
}

function billingImpactLabel(request: AdminPauseRequestView): string {
  if (request.pause_kind === "indefinite") {
    return request.review_on
      ? "Billing defers until admin review"
      : "Missing billing review metadata";
  }
  return request.resume_on
    ? "Billing defers until scheduled resume"
    : "Missing billing resume metadata";
}

function formatDate(value: string): string {
  return new Date(`${value}T00:00:00`).toLocaleDateString(undefined, {
    month: "short",
    day: "numeric",
    year: "numeric",
  });
}

function formatDateTime(value: string): string {
  return new Date(value).toLocaleDateString(undefined, {
    month: "short",
    day: "numeric",
    year: "numeric",
  });
}

function sessionDetail(request: AdminPauseRequestView): string {
  // #860: the enrollment id used to be appended here. Location and start time
  // already identify the class; the id was an internal handle an admin has no
  // way to act on.
  const parts = [
    request.session_location,
    request.session_start_at ? formatDateTime(request.session_start_at) : null,
  ].filter(Boolean);
  return parts.join(" · ") || "No session details";
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
