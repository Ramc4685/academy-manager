"use client";

import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import {
  approveLevelUp,
  getLevelUpQueue,
  rejectLevelUp,
  type LevelUpRecommendation,
} from "@/lib/api/curriculum";
import { Card } from "@/components/ds/card";
import { Chip } from "@/components/ds/chip";
import { Button } from "@/components/ds/button";

export default function AdminLevelUpQueuePage() {
  const queryClient = useQueryClient();

  const { data, isLoading, isError } = useQuery({
    queryKey: ["admin", "level-up-queue"],
    queryFn: () => getLevelUpQueue(),
  });

  const approveMutation = useMutation({
    mutationFn: (recId: string) => approveLevelUp(recId),
    onSuccess: () => void queryClient.invalidateQueries({ queryKey: ["admin", "level-up-queue"] }),
  });

  const rejectMutation = useMutation({
    mutationFn: ({ recId, reason }: { recId: string; reason: string }) =>
      rejectLevelUp(recId, reason),
    onSuccess: () => void queryClient.invalidateQueries({ queryKey: ["admin", "level-up-queue"] }),
  });

  const pending = (data ?? []).filter((r) => r.status === "RECOMMENDED");

  return (
    <section data-testid="admin-level-up-queue" className="space-y-6">
      <div>
        <div className="flex items-center gap-2">
          <h1 className="text-2xl font-semibold">Level-Up Queue</h1>
          {pending.length > 0 && (
            <span className="flex h-6 min-w-[24px] items-center justify-center rounded-full bg-blue-600 px-2 text-xs font-bold text-white">
              {pending.length}
            </span>
          )}
        </div>
        <p className="mt-0.5 text-sm text-neutral-500">
          Pending coach recommendations for level advancement
        </p>
      </div>

      {isError && (
        <p role="alert" className="rounded-md bg-red-50 p-3 text-sm text-red-700">
          Could not load level-up queue.
        </p>
      )}

      {isLoading ? (
        <Skeleton />
      ) : (data ?? []).length === 0 ? (
        <p className="text-sm text-neutral-500" data-testid="level-up-queue-empty">
          No pending level-up recommendations.
        </p>
      ) : (
        <Card p={0}>
          <div className="overflow-x-auto">
            <table className="w-full min-w-[760px] text-sm">
              <thead>
                <tr className="border-b border-neutral-200 text-left dark:border-neutral-800">
                  {["Student", "Program", "From Level", "Recommended By", "Date", "Status", ""].map(
                    (h) => (
                      <th
                        key={h}
                        className="px-4 pb-3 pt-4 font-mono text-[10px] font-bold uppercase tracking-overline text-rally-muted"
                      >
                        {h}
                      </th>
                    ),
                  )}
                </tr>
              </thead>
              <tbody>
                {(data ?? []).map((rec) => (
                  <QueueRow
                    key={rec.rec_id}
                    rec={rec}
                    approvePending={approveMutation.isPending}
                    rejectPending={rejectMutation.isPending}
                    onApprove={() => approveMutation.mutate(rec.rec_id)}
                    onReject={(reason) => rejectMutation.mutate({ recId: rec.rec_id, reason })}
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

function QueueRow({
  rec,
  approvePending,
  rejectPending,
  onApprove,
  onReject,
}: {
  rec: LevelUpRecommendation;
  approvePending: boolean;
  rejectPending: boolean;
  onApprove: () => void;
  onReject: (reason: string) => void;
}) {
  const [showReject, setShowReject] = useState(false);
  const [rejectReason, setRejectReason] = useState("");
  const isPending = rec.status === "RECOMMENDED";
  const disabled = approvePending || rejectPending;

  function handleReject() {
    if (rejectReason.trim()) {
      onReject(rejectReason.trim());
      setShowReject(false);
      setRejectReason("");
    }
  }

  return (
    <tr
      data-testid={`level-up-row-${rec.rec_id}`}
      className="border-b border-neutral-100 last:border-0 dark:border-neutral-800"
    >
      <td className="px-4 py-3 font-medium text-rally-base">{rec.student_id}</td>
      <td className="px-4 py-3 text-rally-subtle">{rec.program_id}</td>
      <td className="px-4 py-3 text-rally-subtle">{rec.from_level_id}</td>
      <td className="px-4 py-3 text-rally-subtle">{rec.recommended_by}</td>
      <td className="px-4 py-3 text-rally-subtle">
        {new Date(rec.recommended_at).toLocaleDateString(undefined, {
          month: "short",
          day: "numeric",
          year: "numeric",
        })}
      </td>
      <td className="px-4 py-3">
        <Chip
          variant={
            rec.status === "approved" ? "approved" : rec.status === "rejected" ? "failed" : "pending"
          }
          label={rec.status.toUpperCase()}
        />
      </td>
      <td className="px-4 py-3">
        {isPending && (
          <div className="space-y-2">
            {!showReject ? (
              <div className="flex justify-end gap-2">
                <Button
                  variant="secondary"
                  size="sm"
                  disabled={disabled}
                  onClick={() => setShowReject(true)}
                >
                  Reject
                </Button>
                <Button
                  variant="primary"
                  size="sm"
                  disabled={disabled}
                  onClick={onApprove}
                >
                  {approvePending ? "..." : "Approve"}
                </Button>
              </div>
            ) : (
              <div className="flex items-center gap-2">
                <input
                  type="text"
                  value={rejectReason}
                  onChange={(e) => setRejectReason(e.target.value)}
                  placeholder="Reason for rejection"
                  className="w-40 rounded-md border border-neutral-300 px-2 py-1 text-xs focus:border-red-400 focus:outline-none"
                  autoFocus
                />
                <Button
                  variant="secondary"
                  size="sm"
                  onClick={() => {
                    setShowReject(false);
                    setRejectReason("");
                  }}
                >
                  Cancel
                </Button>
                <Button
                  variant="primary"
                  size="sm"
                  disabled={!rejectReason.trim() || disabled}
                  onClick={handleReject}
                >
                  {rejectPending ? "..." : "Confirm"}
                </Button>
              </div>
            )}
          </div>
        )}
      </td>
    </tr>
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
