"use client";

import { useQuery } from "@tanstack/react-query";

import { listAdminUsers, listPayouts } from "@/lib/api/admin";
import { Card } from "@/components/ds/card";
import { Avatar } from "@/components/ds/avatar";
import { BigNum } from "@/components/ds/typography";
import { Chip } from "@/components/ds/chip";
import { Skeleton } from "@/components/ds/skeleton";
import { EmptyState } from "@/components/ds/empty-state";

function money(cents: number): string {
  return new Intl.NumberFormat("en-US", { style: "currency", currency: "USD" }).format(cents / 100);
}

/** All-coaches payslip overview, moved from the standalone `/admin/coach-payslip` page onto the Payslips tab of Payouts. */
export function PayslipsPanel() {
  const coachesQuery = useQuery({
    queryKey: ["admin", "users", "coach"],
    queryFn: () => listAdminUsers("coach"),
  });
  const payoutsQuery = useQuery({
    queryKey: ["admin", "finance", "payouts", "coach-payslip"],
    queryFn: listPayouts,
  });

  const coaches = coachesQuery.data?.users ?? [];
  const payouts = payoutsQuery.data?.payouts ?? [];
  const rows = coaches.map((coach) => {
    const payout = payouts.find((row) => row.coach_id === coach.user_id) ?? null;
    return {
      coach,
      payout,
      sessions: payout?.sessions_count ?? 0,
      students: payout?.students_count ?? 0,
      expectedRevenueCents: payout?.expected_revenue_cents ?? 0,
      netEarningsCents: payout?.amount_cents ?? 0,
    };
  });

  const loading = coachesQuery.isLoading || payoutsQuery.isLoading;
  const error = coachesQuery.isError || payoutsQuery.isError;

  return (
    <section data-testid="admin-coach-payslip" className="space-y-5">
      {error ? (
        <p role="alert" className="rounded-md bg-red-50 p-3 text-sm text-red-700">
          Could not load coach payslip data.
        </p>
      ) : loading ? (
        <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
          {[0, 1, 2].map((i) => (
            <Skeleton key={i} variant="block" height="10rem" />
          ))}
        </div>
      ) : rows.length === 0 ? (
        <EmptyState
          data-testid="admin-coach-payslip-empty"
          title="No coaches found."
          compact
        />
      ) : (
        <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
          {rows.map((row) => (
            <Card key={row.coach.user_id} p={20} className="flex flex-col gap-4">
              <div className="flex items-center justify-between">
                <div className="flex items-center gap-3 truncate">
                  <Avatar name={row.coach.display_name || row.coach.email || "Coach"} />
                  <div className="truncate">
                    <div className="font-semibold leading-tight truncate">{row.coach.display_name || row.coach.email}</div>
                    <div className="text-xs text-neutral-500 truncate">
                      {row.coach.email} · {row.sessions} assigned session{row.sessions === 1 ? "" : "s"}
                    </div>
                  </div>
                </div>
                <div className="shrink-0 pl-2">
                  <Chip variant={row.payout?.paid_at ? "paid" : "draft"} label={row.payout?.paid_at ? "PAID" : "DRAFT"} />
                </div>
              </div>

              <div className="mt-2 flex-1">
                <p className="text-xs font-medium uppercase tracking-wide text-neutral-500 mb-1">Net Earnings</p>
                <BigNum size={32}>
                  {money(row.netEarningsCents)}
                </BigNum>
                <p className="mt-1 text-xs text-neutral-500">
                  {row.payout?.rule_label ?? "No payout rule"} · {money(row.expectedRevenueCents)} expected revenue
                </p>
              </div>

              <div className="flex flex-col gap-1 border-t border-neutral-100 pt-3 dark:border-neutral-800 text-sm">
                <div className="flex justify-between items-center">
                  <span className="text-neutral-500">Sessions</span>
                  <span className="font-mono font-medium">{row.sessions}</span>
                </div>
                <div className="flex justify-between items-center">
                  <span className="text-neutral-500">Students</span>
                  <span className="font-mono font-medium">{row.students}</span>
                </div>
              </div>
            </Card>
          ))}
        </div>
      )}
    </section>
  );
}
