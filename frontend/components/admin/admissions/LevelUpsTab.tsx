"use client";

import { useCallback, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import {
  approveLevelUp,
  getLevelUpQueue,
  rejectLevelUp,
  type LevelUpRecommendation,
} from "@/lib/api/curriculum";
import { Card } from "@/components/ds/card";
import { Chip, type ChipVariant } from "@/components/ds/chip";
import { Button } from "@/components/ds/button";
import { ConfirmActionDialog } from "@/components/admin/confirm-action-dialog";
import { actionCellClass, actionHeaderClass } from "@/lib/sticky-action-column";

import { isWithdrawn, reviewErrorMessage, WITHDRAWN_APPROVE_HINT } from "./level-up-review";

const LEVEL_UP_HEADERS = ["Student", "Program", "From Level", "Recommended By", "Date", "Status"];

function levelUpChipVariant(status: LevelUpRecommendation["status"]): ChipVariant {
  switch (status) {
    case "approved":
      return "approved";
    case "rejected":
      return "failed";
    default:
      return "pending";
  }
}

const QUEUE_KEY = ["admin", "level-up-queue"];

export function LevelUpsTab() {
  const queryClient = useQueryClient();
  const [reviewError, setReviewError] = useState<string | null>(null);

  const { data, isLoading, isError } = useQuery({
    queryKey: QUEUE_KEY,
    queryFn: () => getLevelUpQueue(),
  });

  // Always re-read the queue after a decision, win or lose: a 409 means
  // another admin (or our own double-click) already reviewed this row, so the
  // RECOMMENDED row on screen is stale and its Approve button would just
  // produce another 409.
  const refreshQueue = useCallback(
    () => void queryClient.invalidateQueries({ queryKey: QUEUE_KEY }),
    [queryClient],
  );

  const approveMutation = useMutation({
    mutationFn: (recId: string) => approveLevelUp(recId),
    onSuccess: () => {
      setReviewError(null);
      refreshQueue();
    },
    onError: (err: unknown) => {
      setReviewError(reviewErrorMessage(err));
      refreshQueue();
    },
  });

  const rejectMutation = useMutation({
    mutationFn: ({ recId, reason }: { recId: string; reason: string }) =>
      rejectLevelUp(recId, reason),
    onSuccess: () => {
      setReviewError(null);
      refreshQueue();
    },
    onError: (err: unknown) => {
      setReviewError(reviewErrorMessage(err));
      refreshQueue();
    },
  });

  const pending = (data ?? []).filter((r) => r.status === "RECOMMENDED");

  return (
    <div data-testid="admin-level-up-queue-tab" className="space-y-6">
      <div>
        <div className="flex items-center gap-2">
          <h2 className="text-lg font-semibold">Level-up recommendations</h2>
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

      {reviewError && (
        <p
          role="alert"
          data-testid="level-up-review-error"
          className="rounded-md bg-red-50 p-3 text-sm text-red-700"
        >
          {reviewError}
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
                  {LEVEL_UP_HEADERS.map((h) => (
                    <th
                      key={h}
                      className="px-4 pb-3 pt-4 font-mono text-[10px] font-bold uppercase tracking-overline text-rally-muted"
                    >
                      {h}
                    </th>
                  ))}
                  <th
                    className={`px-4 pb-3 pt-4 font-mono text-[10px] font-bold uppercase tracking-overline text-rally-muted ${actionHeaderClass}`}
                  >
                    Actions
                  </th>
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
    </div>
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
  // #838: approving moves the student's level for real, so it asks first.
  const [confirmApprove, setConfirmApprove] = useState(false);
  const isPending = rec.status === "RECOMMENDED";
  const disabled = approvePending || rejectPending;
  // Issue #673: a withdrawn student stays listed so the admin can reject the
  // row, but approval is refused (server-side too — this only saves a 409).
  const withdrawn = isWithdrawn(rec);

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
      <td className="px-4 py-3 font-medium text-rally-base">
        <div className="flex items-center gap-2">
          <span>{rec.student_id}</span>
          {withdrawn && (
            <span data-testid={`level-up-withdrawn-${rec.rec_id}`} title={WITHDRAWN_APPROVE_HINT}>
              <Chip variant="expired" label="Withdrawn" />
            </span>
          )}
        </div>
      </td>
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
        <Chip variant={levelUpChipVariant(rec.status)} label={rec.status.toUpperCase()} />
      </td>
      <td className={`${actionCellClass} bg-white`}>
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
                <span title={withdrawn ? WITHDRAWN_APPROVE_HINT : undefined}>
                  <Button
                    variant="primary"
                    size="sm"
                    disabled={disabled || withdrawn}
                    aria-disabled={withdrawn || undefined}
                    title={withdrawn ? WITHDRAWN_APPROVE_HINT : undefined}
                    onClick={() => setConfirmApprove(true)}
                  >
                    {approvePending ? "..." : "Approve"}
                  </Button>
                </span>
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
        <ConfirmActionDialog
          open={confirmApprove}
          onOpenChange={setConfirmApprove}
          overline="Approve level-up"
          title="Move this student up a level?"
          subject={`${rec.student_id} · ${rec.program_id} · from ${rec.from_level_id}`}
          consequence={
            <>
              <p>
                The student&apos;s pathway level changes for real: coaches mark them against the
                new level&apos;s skills from now on, and the change shows on the family&apos;s
                progress view. No seat, invoice or autopay is touched.
              </p>
              <p>
                Recommended by {rec.recommended_by}. Undoing this means placing the student back by
                hand.
              </p>
            </>
          }
          confirmLabel="Approve level-up"
          confirmVariant="primary"
          pending={approvePending}
          onConfirm={() => {
            onApprove();
            setConfirmApprove(false);
          }}
        />
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
