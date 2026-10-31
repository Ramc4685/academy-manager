"use client";

import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { Button, Card, FormField, Modal, Overline, Skeleton, useToast } from "@/components/ds";
import {
  bpsToPercentInput,
  formatApplicationFee,
  percentInputToBps,
} from "@/lib/application-fee";
import {
  getPlatformApplicationFee,
  setPlatformApplicationFee,
  type ApplicationFee,
} from "@/lib/api/platform";
import { queryKeys } from "@/lib/query/keys";

/**
 * Platform application fee for one academy (roadmap L9b).
 *
 * The share of each online payment routed to the academy's Stripe account
 * that the platform keeps. Default 0%. Only a platform admin can change it;
 * support sees it read-only, and academy admins never see this surface.
 */
export function ApplicationFeeCard({
  academyId,
  canEdit,
}: {
  academyId: string;
  canEdit: boolean;
}) {
  const [editing, setEditing] = useState(false);
  const feeQuery = useQuery({
    queryKey: queryKeys.platform.tenantApplicationFee(academyId),
    queryFn: () => getPlatformApplicationFee(academyId),
    retry: false,
    // Platform-admin only on the API: support gets a 404, so don't ask.
    enabled: canEdit,
  });

  if (!canEdit) return null;

  return (
    <Card p={20}>
      <div data-testid="platform-application-fee">
        <Overline>Platform application fee</Overline>
        {feeQuery.isPending && (
          <div className="mt-3">
            <Skeleton variant="line" lines={1} />
          </div>
        )}
        {feeQuery.isError && (
          <p className="mt-3 text-sm text-rally-subtle">
            The application fee could not be loaded.
          </p>
        )}
        {feeQuery.data && (
          <>
            <p className="mt-3 text-2xl font-bold text-rally-ink" data-testid="application-fee-value">
              {formatApplicationFee(feeQuery.data.application_fee_bps)}
            </p>
            <p className="mt-1 text-sm text-rally-subtle">
              Kept by the platform from each online payment routed to this academy&apos;s
              Stripe account. Rounded down to the cent.
            </p>
            <div className="mt-4">
              <Button variant="secondary" size="sm" onClick={() => setEditing(true)}>
                Change fee
              </Button>
            </div>
          </>
        )}
      </div>
      {editing && feeQuery.data && (
        <EditApplicationFeeDialog fee={feeQuery.data} onClose={() => setEditing(false)} />
      )}
    </Card>
  );
}

function EditApplicationFeeDialog({
  fee,
  onClose,
}: {
  fee: ApplicationFee;
  onClose: () => void;
}) {
  const queryClient = useQueryClient();
  const { toast } = useToast();
  const [percent, setPercent] = useState(bpsToPercentInput(fee.application_fee_bps));
  const [reason, setReason] = useState("");
  const bps = percentInputToBps(percent, fee.max_application_fee_bps);

  const mutation = useMutation({
    mutationFn: () =>
      setPlatformApplicationFee(fee.academy_id, {
        application_fee_bps: bps ?? 0,
        reason: reason.trim() || undefined,
      }),
    onSuccess: (updated) => {
      queryClient.setQueryData(
        queryKeys.platform.tenantApplicationFee(fee.academy_id),
        updated,
      );
      toast({ kind: "success", title: "Application fee updated" });
      onClose();
    },
    onError: (err: Error) => {
      toast({ kind: "error", title: "Could not update fee", description: err.message });
    },
  });

  return (
    <Modal
      open
      onClose={onClose}
      title="Change application fee"
      dismissable={!mutation.isPending}
      footer={
        <div className="flex justify-end gap-2">
          <Button variant="ghost" size="sm" onClick={onClose} disabled={mutation.isPending}>
            Cancel
          </Button>
          <Button
            size="sm"
            disabled={bps === null || mutation.isPending}
            onClick={() => mutation.mutate()}
          >
            {mutation.isPending ? "Saving…" : "Save fee"}
          </Button>
        </div>
      }
    >
      <div className="space-y-3">
        <FormField
          label="Fee (percent)"
          htmlFor="application-fee-percent"
          hint={`0 to ${formatApplicationFee(fee.max_application_fee_bps)}, up to two decimals`}
          required
        >
          <input
            id="application-fee-percent"
            inputMode="decimal"
            className={INPUT_CLASS}
            value={percent}
            onChange={(e) => setPercent(e.target.value)}
          />
        </FormField>
        <FormField label="Reason" htmlFor="application-fee-reason" hint="Kept in the audit trail">
          <input
            id="application-fee-reason"
            className={INPUT_CLASS}
            value={reason}
            onChange={(e) => setReason(e.target.value)}
          />
        </FormField>
      </div>
    </Modal>
  );
}

const INPUT_CLASS =
  "w-full rounded-lg border border-rally-line bg-white px-3 py-2 text-sm text-rally-ink outline-none focus:border-rally-cobalt";
