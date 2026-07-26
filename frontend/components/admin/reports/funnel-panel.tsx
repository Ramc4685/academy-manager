"use client";

import { useQuery } from "@tanstack/react-query";

import { getEnrollmentFunnel } from "@/lib/api/admin";
import { queryKeys } from "@/lib/query/keys";
import { Card } from "@/components/ds/card";
import { Overline, BigNum } from "@/components/ds/typography";
import { Skeleton } from "@/components/ds/skeleton";
import { EmptyState } from "@/components/ds/empty-state";

const STAGES = [
  { key: "leads", label: "Leads" },
  { key: "applied", label: "Applied" },
  { key: "assessed", label: "Assessed" },
  { key: "confirmed", label: "Confirmed" },
] as const;

export function FunnelPanel({ period }: { period: string }) {
  const { data, isLoading, isError } = useQuery({
    queryKey: queryKeys.admin.enrollmentFunnel(period),
    queryFn: () => getEnrollmentFunnel(period),
  });

  return (
    <Card p={24} data-testid="reports-funnel-panel">
      <Overline>Enrollment funnel</Overline>
      <p className="mt-1 text-sm text-rally-subtle">
        Applications moving from lead to confirmed enrollment this month.
      </p>

      {isError ? (
        <p role="alert" className="mt-4 text-sm text-red-700">
          Could not load the enrollment funnel.
        </p>
      ) : isLoading ? (
        <div className="mt-4 space-y-2">
          <Skeleton variant="block" height="6rem" />
        </div>
      ) : !data || data.total_applications === 0 ? (
        <EmptyState
          className="mt-4"
          title="No applications this period"
          description="Applications will appear here once families begin enrolling."
        />
      ) : (
        <div className="mt-4 space-y-4">
          <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
            {STAGES.map((stage) => (
              <div key={stage.key} className="rounded-md border border-rally-line p-3">
                <Overline>{stage.label}</Overline>
                <BigNum size={24}>{formatInteger(data[stage.key])}</BigNum>
              </div>
            ))}
          </div>
          <div className="flex flex-wrap items-center gap-4 border-t border-rally-line pt-4 text-sm text-rally-subtle">
            <span>
              <span className="font-semibold text-rally-ink">{formatPercent(data.conversion_rate)}</span>{" "}
              conversion rate
            </span>
            <span>{formatInteger(data.dropped)} dropped</span>
            <span>{formatInteger(data.total_applications)} total applications</span>
          </div>
        </div>
      )}
    </Card>
  );
}

function formatInteger(value: number): string {
  return new Intl.NumberFormat("en-US").format(value);
}

function formatPercent(value: number): string {
  return new Intl.NumberFormat("en-US", { style: "percent", maximumFractionDigits: 0 }).format(
    value,
  );
}
