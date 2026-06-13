"use client";

import { useQuery } from "@tanstack/react-query";

import { AdminUsersDirectory } from "@/components/admin/AdminUsersDirectory";
import { getCoachEngagementStats } from "@/lib/api/admin-teaching";
import { queryKeys } from "@/lib/query/keys";

export default function AdminCoachesPage() {
  return (
    <section className="space-y-6">
      <CoachEngagementStatsStrip />
      <AdminUsersDirectory fixedRole="coach" />
    </section>
  );
}

function CoachEngagementStatsStrip() {
  const ranges = getEngagementRanges();
  const sevenDay = useQuery({
    queryKey: queryKeys.admin.coachEngagement(ranges.seven.startDate, ranges.seven.endDate),
    queryFn: () => getCoachEngagementStats(ranges.seven),
    staleTime: 5 * 60 * 1000,
  });
  const thirtyDay = useQuery({
    queryKey: queryKeys.admin.coachEngagement(ranges.thirty.startDate, ranges.thirty.endDate),
    queryFn: () => getCoachEngagementStats(ranges.thirty),
    staleTime: 5 * 60 * 1000,
  });

  const sevenTotal = sumOutcomes(sevenDay.data?.rows ?? []);
  const thirtyTotal = sumOutcomes(thirtyDay.data?.rows ?? []);
  const activeCoaches7 = sevenDay.data?.rows.length ?? 0;
  const activeCoaches30 = thirtyDay.data?.rows.length ?? 0;

  return (
    <div className="grid grid-cols-1 gap-3 md:grid-cols-3" data-testid="coach-engagement-stats">
      <StatsTile
        label="Skill statuses updated"
        value={sevenDay.isLoading ? "..." : String(sevenTotal)}
        detail="Last 7 days"
      />
      <StatsTile
        label="Skill statuses updated"
        value={thirtyDay.isLoading ? "..." : String(thirtyTotal)}
        detail="Last 30 days"
      />
      <StatsTile
        label="Coaches active"
        value={
          sevenDay.isLoading || thirtyDay.isLoading
            ? "..."
            : `${activeCoaches7}/${activeCoaches30}`
        }
        detail="7d / 30d"
      />
      {(sevenDay.isError || thirtyDay.isError) && (
        <p role="alert" className="md:col-span-3 rounded-md bg-red-50 p-3 text-sm text-red-700">
          Could not load coach engagement stats.
        </p>
      )}
    </div>
  );
}

function StatsTile({
  label,
  value,
  detail,
}: {
  label: string;
  value: string;
  detail: string;
}) {
  return (
    <div className="rounded-md border border-rally-line bg-white p-4">
      <p className="font-mono text-[10px] font-bold uppercase tracking-overline text-rally-muted">
        {label}
      </p>
      <p className="mt-2 font-display text-2xl font-semibold text-rally-ink">{value}</p>
      <p className="mt-1 text-sm text-rally-muted">{detail}</p>
    </div>
  );
}

function getEngagementRanges() {
  const end = new Date();
  const seven = new Date(end);
  seven.setDate(end.getDate() - 6);
  const thirty = new Date(end);
  thirty.setDate(end.getDate() - 29);
  return {
    seven: { startDate: dateOnly(seven), endDate: dateOnly(end) },
    thirty: { startDate: dateOnly(thirty), endDate: dateOnly(end) },
  };
}

function dateOnly(value: Date): string {
  const year = value.getFullYear();
  const month = String(value.getMonth() + 1).padStart(2, "0");
  const day = String(value.getDate()).padStart(2, "0");
  return `${year}-${month}-${day}`;
}

function sumOutcomes(rows: { outcomes_recorded: number }[]) {
  return rows.reduce((total, row) => total + row.outcomes_recorded, 0);
}
