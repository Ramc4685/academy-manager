"use client";

import { useMemo } from "react";
import { useQuery } from "@tanstack/react-query";

import { getCoachUtilization, listAdminUsers } from "@/lib/api/admin";
import { queryKeys } from "@/lib/query/keys";
import { Card } from "@/components/ds/card";
import { Overline } from "@/components/ds/typography";
import { Skeleton } from "@/components/ds/skeleton";
import { EmptyState } from "@/components/ds/empty-state";

export function CoachUtilizationPanel({ periods }: { periods: string[] }) {
  const { data, isLoading, isError } = useQuery({
    queryKey: queryKeys.admin.coachUtilization(periods),
    queryFn: () => getCoachUtilization(periods),
  });

  const coachesQuery = useQuery({
    queryKey: queryKeys.admin.users("coach"),
    queryFn: () => listAdminUsers("coach"),
  });

  const coachNames = useMemo(() => {
    const map = new Map<string, string>();
    for (const coach of coachesQuery.data?.users ?? []) {
      map.set(coach.user_id, coach.display_name);
    }
    return map;
  }, [coachesQuery.data]);

  const rows = data?.coaches ?? [];

  return (
    <Card p={24} data-testid="reports-coach-utilization-panel">
      <div className="flex items-center justify-between gap-3">
        <div>
          <Overline>Coach utilization</Overline>
          <p className="mt-1 text-sm text-rally-subtle">
            Hours coached and payout across the last {periods.length} months.
          </p>
        </div>
        {data ? (
          <span className="text-sm font-semibold text-rally-ink">
            {formatCurrency(data.total_payout_minor)} total payout
          </span>
        ) : null}
      </div>

      {isError ? (
        <p role="alert" className="mt-4 text-sm text-red-700">
          Could not load coach utilization.
        </p>
      ) : isLoading ? (
        <div className="mt-4 space-y-2">
          <Skeleton variant="block" height="6rem" />
        </div>
      ) : rows.length === 0 ? (
        <EmptyState
          className="mt-4"
          title="No coach activity recorded"
          description="Utilization will appear here once coaches run sessions."
        />
      ) : (
        <div className="mt-4 overflow-x-auto">
          <table className="w-full min-w-[420px] text-left text-sm">
            <thead className="text-xs uppercase text-rally-muted">
              <tr>
                <th className="px-2 py-2">Coach</th>
                <th className="px-2 py-2">Period</th>
                <th className="px-2 py-2">Hours</th>
                <th className="px-2 py-2">Payout</th>
                <th className="px-2 py-2">Utilization</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-rally-line">
              {rows.map((row) => (
                <tr key={`${row.coach_id}-${row.period}`}>
                  <td className="px-2 py-2 font-medium text-rally-ink">
                    {coachNames.get(row.coach_id) ?? row.coach_id}
                  </td>
                  <td className="px-2 py-2 text-rally-muted">{row.period}</td>
                  <td className="px-2 py-2 text-rally-muted">{formatHours(row.hours)}</td>
                  <td className="px-2 py-2 text-rally-muted">{formatCurrency(row.payout_minor)}</td>
                  <td className="px-2 py-2 text-rally-muted">{formatPercent(row.utilization_rate)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </Card>
  );
}

function formatHours(value: number): string {
  return new Intl.NumberFormat("en-US", { maximumFractionDigits: 1 }).format(value);
}

function formatCurrency(cents: number): string {
  return new Intl.NumberFormat("en-US", { style: "currency", currency: "USD" }).format(cents / 100);
}

function formatPercent(value: number): string {
  return new Intl.NumberFormat("en-US", { style: "percent", maximumFractionDigits: 0 }).format(
    value,
  );
}
