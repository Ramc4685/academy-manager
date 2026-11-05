"use client";

import Link from "next/link";
import { useQuery } from "@tanstack/react-query";

import { getAdminAiUsage, type AiUsage } from "@/lib/api/admin";
import { queryKeys } from "@/lib/query/keys";
import { useIsOwner } from "@/components/admin/owner-context";
import { Card } from "@/components/ds/card";
import { Overline } from "@/components/ds/typography";

/**
 * Read-only AI usage meter (plan 2026-11-04 Phase 2, slice A3): this month's
 * drafts against the plan's cap. The free cap is a soft prompt to upgrade,
 * never a hard stop; Growth shows the abuse ceiling.
 */
export function AiUsageMeter({ usage }: { usage: AiUsage }) {
  // Integrations (where the Plan card lives) is an owner-only panel; a non-owner would land on OwnerOnlyPanel.
  const isOwner = useIsOwner();
  return (
    <>
      <p className="mt-3 text-sm text-rally-ink" data-testid="ai-usage-line">
        You have used {usage.used} of {usage.cap} AI drafts this month
        {usage.tier === "growth" ? " (Growth plan)" : ""}.
      </p>
      {usage.upgrade_suggested && (
        <p className="mt-2 text-sm text-rally-subtle" data-testid="ai-usage-upgrade">
          {isOwner ? (
            <Link href="/admin/settings?panel=integrations" className="font-medium text-rally-cobalt underline">
              Upgrade to Growth for unlimited drafts
            </Link>
          ) : (
            "Ask the academy owner to upgrade to Growth for unlimited drafts."
          )}
        </p>
      )}
    </>
  );
}

export function AiUsageCard() {
  const query = useQuery({ queryKey: queryKeys.admin.aiUsage(), queryFn: getAdminAiUsage });

  return (
    <Card p={24} className="max-w-3xl" data-testid="admin-settings-ai-usage">
      <Overline>AI drafts</Overline>
      {query.isLoading ? (
        <div className="mt-5 h-10 animate-pulse rounded-md bg-rally-paper" />
      ) : query.isError ? (
        <p role="alert" className="mt-4 text-sm font-medium text-red-700">
          Could not load AI usage.
        </p>
      ) : query.data ? (
        <AiUsageMeter usage={query.data} />
      ) : null}
    </Card>
  );
}
