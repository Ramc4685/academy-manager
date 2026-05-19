"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import {
  approvePauseRequest,
  declinePauseRequest,
  listAdminPauseRequests,
  type AdminPauseRequestView,
} from "@/lib/api/admin";

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
    <section data-testid="admin-pause-requests" className="space-y-5">
      <div>
        <h1 className="text-2xl font-semibold">Pause requests</h1>
        <p className="mt-1 text-sm text-neutral-500">
          Parent pause requests reviewed through the enrollment BFF.
        </p>
      </div>

      {isError ? (
        <p role="alert" className="rounded-md bg-red-50 p-3 text-sm text-red-700">
          Could not load pause requests.
        </p>
      ) : isLoading ? (
        <Skeleton />
      ) : requests.length === 0 ? (
        <p className="text-sm text-neutral-500">No pending pause requests.</p>
      ) : (
        <div className="overflow-x-auto rounded-lg border border-neutral-200 bg-white dark:border-neutral-800 dark:bg-neutral-900">
          <table className="w-full min-w-[840px] text-sm">
            <thead>
              <tr className="border-b border-neutral-200 text-left text-neutral-500 dark:border-neutral-800">
                <th className="px-4 py-3 font-medium">Request</th>
                <th className="px-4 py-3 font-medium">Period</th>
                <th className="px-4 py-3 font-medium">Reason</th>
                <th className="px-4 py-3 font-medium">Status</th>
                <th className="px-4 py-3 font-medium sr-only">Actions</th>
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
      )}
    </section>
  );
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
    <tr className="border-b border-neutral-100 last:border-0 dark:border-neutral-800">
      <td className="px-4 py-3">
        <div className="font-mono text-xs text-neutral-500">{request.pause_request_id}</div>
        <div className="mt-1 text-xs text-neutral-500">
          Parent {request.parent_id.slice(0, 14)} · enrollment {request.enrollment_id.slice(0, 14)}
        </div>
      </td>
      <td className="px-4 py-3 font-medium">{request.period}</td>
      <td className="px-4 py-3 text-neutral-600 dark:text-neutral-300">{request.reason || "-"}</td>
      <td className="px-4 py-3">
        <StatusBadge status={request.status} />
      </td>
      <td className="px-4 py-3">
        {isPending ? (
          <div className="flex justify-end gap-2">
            <button
              type="button"
              onClick={onDecline}
              disabled={disabled}
              className="min-h-touch rounded-md border border-neutral-300 px-3 text-sm hover:bg-neutral-50 disabled:opacity-60 dark:border-neutral-700 dark:hover:bg-neutral-800"
            >
              Decline
            </button>
            <button
              type="button"
              onClick={onApprove}
              disabled={disabled}
              className="min-h-touch rounded-md bg-blue-600 px-3 text-sm font-medium text-white hover:bg-blue-700 disabled:opacity-60"
            >
              Approve
            </button>
          </div>
        ) : null}
      </td>
    </tr>
  );
}

function StatusBadge({ status }: { status: string }) {
  const palette: Record<string, string> = {
    pending: "bg-amber-100 text-amber-800 dark:bg-amber-900 dark:text-amber-100",
    approved: "bg-emerald-100 text-emerald-800 dark:bg-emerald-900 dark:text-emerald-100",
    declined: "bg-neutral-100 text-neutral-800 dark:bg-neutral-800 dark:text-neutral-100",
  };
  return <span className={`rounded-full px-2 py-0.5 text-xs ${palette[status] ?? palette.declined}`}>{status}</span>;
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
