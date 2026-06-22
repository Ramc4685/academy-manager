"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import {
  approvePauseRequest,
  declinePauseRequest,
  listAdminPauseRequests,
  type AdminPauseRequestView,
} from "@/lib/api/admin";
import { Card } from "@/components/ds/card";
import { Chip } from "@/components/ds/chip";
import { Button } from "@/components/ds/button";

export default function AdminPauseRequestsPage() {
  const queryClient = useQueryClient();
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
    <section data-testid="admin-pause-requests" className="space-y-6">
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
                  <th className="px-2 pb-3 font-mono text-[10px] font-bold uppercase tracking-overline text-rally-muted sr-only">Actions</th>
                </tr>
              </thead>
              <tbody>
                {requests.map((request) => (
                  <PauseRow
                    key={request.pause_request_id}
                    request={request}
                    disabled={approveMutation.isPending || declineMutation.isPending}
                    onApprove={() => approveMutation.mutate(request.pause_request_id)}
                    onDecline={() => declineMutation.mutate(request.pause_request_id)}
                  />
                ))}
              </tbody>
            </table>
          </div>
        </Card>
      )}
    </section>
  );
}

function mapStatus(status: string): any {
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
      <td className="px-2 py-3">
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
  const parts = [
    request.session_location,
    request.session_start_at ? formatDateTime(request.session_start_at) : null,
    request.enrollment_id ? `Enrollment ${request.enrollment_id}` : null,
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
