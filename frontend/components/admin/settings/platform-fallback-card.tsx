"use client";

import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { getPlatformChargeFallback, setPlatformChargeFallback } from "@/lib/api/admin";
import { queryKeys } from "@/lib/query/keys";
import { Button } from "@/components/ds/button";
import { Card } from "@/components/ds/card";
import { Modal } from "@/components/ds/modal";
import { Overline } from "@/components/ds/typography";

function getErrorMessage(error: unknown): string {
  if (error instanceof Error) return error.message;
  return "Something went wrong. Please try again.";
}

export function PlatformFallbackCard() {
  const queryClient = useQueryClient();
  const [confirmOpen, setConfirmOpen] = useState(false);
  const [reason, setReason] = useState("");

  const query = useQuery({
    queryKey: queryKeys.admin.platformFallback(),
    queryFn: getPlatformChargeFallback,
  });
  const allowFallback = query.data?.allow_platform_charge_fallback ?? false;

  const mutation = useMutation({
    mutationFn: setPlatformChargeFallback,
    onSuccess: (data) => {
      queryClient.setQueryData(queryKeys.admin.platformFallback(), data);
      setConfirmOpen(false);
      setReason("");
    },
  });

  function openConfirm() {
    mutation.reset();
    setReason("");
    setConfirmOpen(true);
  }

  function closeConfirm() {
    if (mutation.isPending) return;
    setConfirmOpen(false);
  }

  const nextEnabled = !allowFallback;
  const reasonTrimmed = reason.trim();

  return (
    <Card p={24} className="max-w-3xl" data-testid="admin-settings-platform-fallback">
      <Overline>Platform charge fallback</Overline>

      {query.isLoading ? (
        <div className="mt-5 h-20 animate-pulse rounded-md bg-rally-paper" />
      ) : query.isError ? (
        <p role="alert" className="mt-4 text-sm font-medium text-red-700">
          Could not load the platform fallback setting.
        </p>
      ) : (
        <div className="mt-5 space-y-4">
          <div className="flex flex-wrap items-start justify-between gap-3">
            <div>
              <p className="font-display text-[18px] font-semibold text-rally-ink">
                Fallback to platform account
              </p>
              <p className="mt-1 max-w-xl text-sm text-rally-muted">
                When ON, parent charges route to the platform Stripe account if this
                academy&apos;s connected account isn&apos;t charge-ready. Funds temporarily
                park in the platform account instead of failing closed — treat this as a
                short-lived escape hatch, not a steady state.
              </p>
            </div>
            <span
              className={`inline-flex items-center gap-1.5 rounded-full px-3 py-1 font-mono text-[10px] font-bold uppercase tracking-overline ${
                allowFallback
                  ? "bg-status-red-50 text-status-red-800"
                  : "bg-status-green-50 text-status-green-800"
              }`}
            >
              <span
                className={`size-1.5 rounded-full ${allowFallback ? "bg-status-red-500" : "bg-status-green-500"}`}
              />
              {allowFallback ? "ON — routing to platform" : "OFF"}
            </span>
          </div>

          <Button variant={allowFallback ? "danger" : "secondary"} size="sm" onClick={openConfirm}>
            {allowFallback ? "Turn off fallback" : "Turn on fallback"}
          </Button>
        </div>
      )}

      <Modal
        open={confirmOpen}
        onClose={closeConfirm}
        title={nextEnabled ? "Turn on platform charge fallback?" : "Turn off platform charge fallback?"}
        size="sm"
        footer={
          <div className="flex justify-end gap-2">
            <Button variant="secondary" size="sm" onClick={closeConfirm} disabled={mutation.isPending}>
              Cancel
            </Button>
            <Button
              variant={nextEnabled ? "danger" : "primary"}
              size="sm"
              disabled={!reasonTrimmed || mutation.isPending}
              onClick={() => mutation.mutate({ enabled: nextEnabled, reason: reasonTrimmed })}
            >
              {mutation.isPending ? "Saving..." : "Confirm"}
            </Button>
          </div>
        }
      >
        <div className="space-y-3">
          <p className="text-sm text-rally-muted">
            {nextEnabled
              ? "Parent charges for this academy will route to the platform Stripe account whenever the connected account isn't charge-ready. This is audited."
              : "Charges will fail closed instead of falling back to the platform account when the connected account isn't charge-ready. This is audited."}
          </p>
          <label className="grid gap-1.5 text-sm font-medium text-rally-ink">
            Reason (required)
            <textarea
              value={reason}
              onChange={(event) => setReason(event.target.value)}
              rows={3}
              placeholder="Why are you changing this now?"
              className="rounded-md border border-rally-line bg-white px-3 py-2 text-sm outline-none focus:border-blue-500"
            />
          </label>
          {mutation.isError && (
            <p role="alert" className="text-sm font-medium text-red-700">
              {getErrorMessage(mutation.error)}
            </p>
          )}
        </div>
      </Modal>
    </Card>
  );
}
