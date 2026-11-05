"use client";

import { useQuery } from "@tanstack/react-query";

import { getAdminPlatformFee } from "@/lib/api/admin";
import { formatProcessingRate } from "@/lib/application-fee";
import { formatDateOnly } from "@/lib/money";
import { queryKeys } from "@/lib/query/keys";
import { Card } from "@/components/ds/card";
import { Overline } from "@/components/ds/typography";

/**
 * Read-only: the CourtMastr processing markup this academy pays on Stripe-
 * collected payments, the agreement it rests on, and whether the academy has
 * accepted it (AI strategy Phase 2 A1). Only a platform admin can change it.
 */
export function ProcessingFeeCard() {
  const query = useQuery({
    queryKey: queryKeys.admin.platformFee(),
    queryFn: getAdminPlatformFee,
  });
  const fee = query.data;

  return (
    <Card p={24} className="max-w-3xl" data-testid="admin-settings-processing-fee">
      <Overline>CourtMastr processing fee</Overline>

      {query.isLoading ? (
        <div className="mt-5 h-20 animate-pulse rounded-md bg-rally-paper" />
      ) : query.isError || typeof fee?.application_fee_bps !== "number" ? (
        <p role="alert" className="mt-4 text-sm font-medium text-red-700">
          Could not load the processing fee.
        </p>
      ) : (
        <div className="mt-5 space-y-3">
          <p
            className="font-display text-[18px] font-semibold text-rally-ink"
            data-testid="admin-settings-processing-fee-rate"
          >
            CourtMastr processing fee: {formatProcessingRate(fee.application_fee_bps)} of card and
            ACH payments. Parents are not charged a per-order fee.
          </p>
          <p className="max-w-xl text-sm text-rally-muted">{fee.agreement_text}</p>
          <p className="text-sm text-rally-subtle" data-testid="admin-settings-processing-fee-acceptance">
            {fee.accepted_by && fee.accepted_at
              ? `Agreement ${fee.agreement_version ?? ""} accepted by ${fee.accepted_by} on ${formatDateOnly(fee.accepted_at)}.`
              : "Agreement not yet accepted."}
          </p>
        </div>
      )}
    </Card>
  );
}
