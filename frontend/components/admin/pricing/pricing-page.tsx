"use client";

import { useQuery } from "@tanstack/react-query";

import { Card, TableSkeleton } from "@/components/ds";
import { ClassPricesCard } from "@/components/admin/pricing/class-prices-card";
import { PlansCard } from "@/components/admin/pricing/plans-card";
import { SavedOverridesCard } from "@/components/admin/pricing/saved-overrides-card";
import { OwnerOnlyPanel, useIsOwner } from "@/components/admin/owner-context";
import { getPricingOverview } from "@/lib/api/v2/pricing";
import { queryKeys } from "@/lib/query/keys";

/**
 * Pricing under Money (Settings overhaul Phase 3 PR 11b): the plan list,
 * where each class's price comes from, and saved overrides to review.
 * Owner only: the shell swaps the page for the owner-only panel for anyone
 * else (`OWNER_ONLY_ROUTE_PREFIXES`), and the BFF 403s them too.
 */
export function PricingPage() {
  const isOwner = useIsOwner();
  const query = useQuery({
    queryKey: queryKeys.admin.pricing(),
    queryFn: getPricingOverview,
    enabled: isOwner,
    retry: false,
  });

  if (!isOwner) return <OwnerOnlyPanel />;

  const overview = query.data;
  const linkedCounts = Object.fromEntries(
    (overview?.plans ?? []).map((plan) => [plan.plan_id, plan.linked_classes]),
  );

  return (
    <section data-testid="admin-pricing" className="space-y-6">
      <PlansCard linkedCounts={linkedCounts} />
      {query.isPending ? (
        <Card>
          <TableSkeleton rows={4} cols={4} />
        </Card>
      ) : query.isError || !overview ? (
        <Card>
          <p role="alert" data-testid="pricing-error" className="text-sm text-status-red-800">
            Could not load class prices. Refresh to try again.
          </p>
        </Card>
      ) : (
        <>
          <ClassPricesCard
            classes={overview.classes}
            plans={overview.plans}
            autoLinkable={overview.auto_linkable}
          />
          <SavedOverridesCard overrides={overview.saved_overrides} />
        </>
      )}
    </section>
  );
}
