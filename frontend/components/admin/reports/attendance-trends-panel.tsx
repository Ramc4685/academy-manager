"use client";

import { useQuery } from "@tanstack/react-query";

import { getAttendanceTrends } from "@/lib/api/admin";
import { queryKeys } from "@/lib/query/keys";
import { Card } from "@/components/ds/card";
import { Overline } from "@/components/ds/typography";
import { Skeleton } from "@/components/ds/skeleton";
import { EmptyState } from "@/components/ds/empty-state";

export function AttendanceTrendsPanel({ periods }: { periods: string[] }) {
  const { data, isLoading, isError } = useQuery({
    queryKey: queryKeys.admin.attendanceTrends(periods),
    queryFn: () => getAttendanceTrends(periods),
  });

  const rows = data?.periods ?? [];

  return (
    <Card p={24} data-testid="reports-attendance-trends-panel">
      <div className="flex items-center justify-between gap-3">
        <div>
          <Overline>Attendance trends</Overline>
          <p className="mt-1 text-sm text-rally-subtle">
            Session completion vs no-shows over the last {periods.length} months.
          </p>
        </div>
        {data ? (
          <span className="text-sm font-semibold text-rally-ink">
            {formatPercent(data.overall_completion_rate)} overall
          </span>
        ) : null}
      </div>

      {isError ? (
        <p role="alert" className="mt-4 text-sm text-red-700">
          Could not load attendance trends.
        </p>
      ) : isLoading ? (
        <div className="mt-4 space-y-2">
          <Skeleton variant="block" height="6rem" />
        </div>
      ) : rows.length === 0 ? (
        <EmptyState
          className="mt-4"
          title="No attendance recorded"
          description="Completion rates will appear here once sessions are marked."
        />
      ) : (
        <div className="mt-4 overflow-x-auto">
          <table className="w-full min-w-[420px] text-left text-sm">
            <thead className="text-xs uppercase text-rally-muted">
              <tr>
                <th className="px-2 py-2">Period</th>
                <th className="px-2 py-2">Scheduled</th>
                <th className="px-2 py-2">Completed</th>
                <th className="px-2 py-2">No-shows</th>
                <th className="px-2 py-2">Completion rate</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-rally-line">
              {rows.map((row) => (
                <tr key={row.period}>
                  <td className="px-2 py-2 font-medium text-rally-ink">{row.period}</td>
                  <td className="px-2 py-2 text-rally-muted">{formatInteger(row.scheduled_count)}</td>
                  <td className="px-2 py-2 text-rally-muted">{formatInteger(row.completed_count)}</td>
                  <td className="px-2 py-2 text-rally-muted">{formatInteger(row.no_show_count)}</td>
                  <td className="px-2 py-2 text-rally-muted">{formatPercent(row.completion_rate)}</td>
                </tr>
              ))}
            </tbody>
          </table>
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
