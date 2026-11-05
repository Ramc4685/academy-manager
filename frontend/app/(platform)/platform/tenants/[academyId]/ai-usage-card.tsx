"use client";

import { useQuery } from "@tanstack/react-query";

import { Card, Overline, Skeleton } from "@/components/ds";
import { AiUsageMeter } from "@/components/admin/settings/ai-usage-card";
import { getPlatformAiUsage } from "@/lib/api/platform";
import { queryKeys } from "@/lib/query/keys";

/** Platform view of an academy's AI usage meter (Phase 2 slice A3). */
export function AiUsageCard({ academyId, canEdit }: { academyId: string; canEdit: boolean }) {
  const query = useQuery({
    queryKey: queryKeys.platform.tenantAiUsage(academyId),
    queryFn: () => getPlatformAiUsage(academyId),
    retry: false,
    // Platform-admin only on the API: support gets a 404, so don't ask.
    enabled: canEdit,
  });

  if (!canEdit) return null;

  return (
    <Card p={20}>
      <div data-testid="platform-ai-usage">
        <Overline>AI drafts</Overline>
        {query.isPending && (
          <div className="mt-3">
            <Skeleton variant="line" lines={1} />
          </div>
        )}
        {query.isError && (
          <p className="mt-3 text-sm text-rally-subtle">AI usage could not be loaded.</p>
        )}
        {query.data && <AiUsageMeter usage={query.data} />}
      </div>
    </Card>
  );
}
