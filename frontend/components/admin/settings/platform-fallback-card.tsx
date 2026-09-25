"use client";

import { useQuery } from "@tanstack/react-query";

import { getPlatformChargeFallback } from "@/lib/api/admin";
import { queryKeys } from "@/lib/query/keys";
import { Card } from "@/components/ds/card";
import { Overline } from "@/components/ds/typography";

/**
 * Read-only: where this academy's card payments settle. Only the house
 * academy (the platform owner's own academy) charges on the platform Stripe
 * account; that is a deploy-time setting, not something an academy can toggle.
 */
export function PlatformFallbackCard() {
  const query = useQuery({
    queryKey: queryKeys.admin.platformFallback(),
    queryFn: getPlatformChargeFallback,
  });
  const houseAcademy = query.data?.allow_platform_charge_fallback ?? false;

  return (
    <Card p={24} className="max-w-3xl" data-testid="admin-settings-platform-fallback">
      <Overline>Where payments settle</Overline>

      {query.isLoading ? (
        <div className="mt-5 h-20 animate-pulse rounded-md bg-rally-paper" />
      ) : query.isError ? (
        <p role="alert" className="mt-4 text-sm font-medium text-red-700">
          Could not load where payments settle.
        </p>
      ) : (
        <div className="mt-5 flex flex-wrap items-start justify-between gap-3">
          <div>
            <p className="font-display text-[18px] font-semibold text-rally-ink">
              {houseAcademy ? "CourtMastr platform account" : "Your connected Stripe account"}
            </p>
            <p className="mt-1 max-w-xl text-sm text-rally-muted">
              {houseAcademy
                ? "This is the house academy: parent card payments, saved cards and autopay are collected on the CourtMastr platform Stripe account. It does not connect a separate Stripe account."
                : "Parent card payments go to the Stripe account connected above. Until it is connected and ready for charges, card payments and autopay are paused."}
            </p>
          </div>
          <span
            data-testid="admin-settings-platform-fallback-status"
            className="inline-flex items-center gap-1.5 rounded-full bg-rally-paper px-3 py-1 font-mono text-[10px] font-bold uppercase tracking-overline text-rally-ink"
          >
            {houseAcademy ? "House academy" : "Connected account"}
          </span>
        </div>
      )}
    </Card>
  );
}
