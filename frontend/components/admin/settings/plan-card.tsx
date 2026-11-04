"use client";

import { useSearchParams } from "next/navigation";
import { useState } from "react";
import { useMutation, useQuery } from "@tanstack/react-query";

import { getAdminPlan, startGrowthCheckout } from "@/lib/api/admin";
import { queryKeys } from "@/lib/query/keys";
import { Button } from "@/components/ds/button";
import { Card } from "@/components/ds/card";
import { Overline } from "@/components/ds/typography";

const STATUS_LABEL: Record<string, string> = {
  trialing: "Trial",
  active: "Active",
  past_due: "Payment past due",
  unpaid: "Unpaid",
  incomplete: "Checkout not finished",
  cancelled: "Cancelled",
};

function dollars(cents: number): string {
  return "$" + Math.round(cents / 100);
}

/**
 * What the academy pays CourtMastr (owner only, AI strategy Phase 2 A2):
 * the current plan or free core operations, and the Growth pitch with a
 * Stripe Billing checkout. The webhook moves the row to active after the
 * redirect, so the card refetches on return.
 */
export function PlanCard() {
  const searchParams = useSearchParams();
  const planParam = searchParams.get("plan");
  const [checkoutError, setCheckoutError] = useState<string | null>(null);

  const query = useQuery({
    queryKey: queryKeys.admin.plan(),
    queryFn: getAdminPlan,
    refetchOnWindowFocus: planParam === "upgraded",
  });
  const overview = query.data;

  const checkout = useMutation({
    mutationFn: startGrowthCheckout,
    onSuccess: (data) => {
      window.location.href = data.url;
    },
    onError: (error: unknown) => {
      const message = error instanceof Error ? error.message : "";
      setCheckoutError(
        message.includes("already")
          ? "This academy is already on the Growth plan."
          : "Could not start checkout. Please try again.",
      );
    },
  });

  const onGrowth =
    overview?.plan?.code === "growth" &&
    (overview.subscription?.billing_status === "active" ||
      overview.subscription?.billing_status === "trialing");
  const growthPrice = overview?.growth ? dollars(overview.growth.monthly_price_cents) : "$99";

  return (
    <Card p={24} className="max-w-3xl" data-testid="admin-settings-plan">
      <Overline>Your CourtMastr plan</Overline>

      {query.isLoading ? (
        <div className="mt-5 h-24 animate-pulse rounded-md bg-rally-paper" />
      ) : query.isError || !overview ? (
        <p role="alert" className="mt-4 text-sm font-medium text-red-700">
          Could not load your plan.
        </p>
      ) : (
        <div className="mt-5 space-y-5">
          {planParam === "upgraded" && !onGrowth && (
            <p className="rounded-md bg-green-50 px-3 py-2 text-sm font-medium text-green-700">
              Thanks. Stripe is confirming your subscription; this updates in a moment.
            </p>
          )}
          {checkoutError && (
            <p role="alert" className="rounded-md bg-red-50 px-3 py-2 text-sm font-medium text-red-700">
              {checkoutError}
            </p>
          )}

          <div>
            <p
              data-testid="admin-settings-plan-current"
              className="font-display text-[18px] font-semibold text-rally-ink"
            >
              {overview.plan
                ? `${overview.plan.display_name} · ${dollars(overview.plan.monthly_price_cents)} a month`
                : "Free (core operations)"}
            </p>
            {overview.subscription && (
              <p className="mt-1 text-sm text-rally-muted">
                {STATUS_LABEL[overview.subscription.billing_status] ??
                  overview.subscription.billing_status}
                {overview.subscription.cancel_at_period_end &&
                  overview.subscription.current_period_end &&
                  ` · ends ${new Date(overview.subscription.current_period_end).toLocaleDateString()}`}
              </p>
            )}
          </div>

          {!onGrowth && (
            <div className="flex flex-wrap items-start justify-between gap-3 rounded-md bg-rally-paper p-4">
              <div>
                <p className="font-display text-[16px] font-semibold text-rally-ink">
                  Growth · {growthPrice} a month
                </p>
                <ul className="mt-1 list-disc pl-5 text-sm text-rally-muted">
                  <li>0 bps processing markup on card and bank payments</li>
                  <li>AI features as they ship</li>
                </ul>
              </div>
              {overview.checkout_available ? (
                <Button
                  type="button"
                  data-testid="admin-settings-plan-upgrade"
                  onClick={() => {
                    setCheckoutError(null);
                    checkout.mutate();
                  }}
                  disabled={checkout.isPending}
                >
                  {checkout.isPending ? "Opening checkout..." : "Upgrade to Growth"}
                </Button>
              ) : (
                <p className="text-sm text-rally-muted" data-testid="admin-settings-plan-unavailable">
                  Growth checkout is not open yet. Contact CourtMastr to upgrade.
                </p>
              )}
            </div>
          )}
        </div>
      )}
    </Card>
  );
}
