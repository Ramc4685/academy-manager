"use client";

import { useQuery } from "@tanstack/react-query";

import { listAdminUsers } from "@/lib/api/admin";
import { listMonthlyPayroll } from "@/lib/api/v2/payroll";
import { payslipChipFor } from "@/lib/payslip-chip";
import { money } from "@/lib/format-money";
import { Card } from "@/components/ds/card";
import { Avatar } from "@/components/ds/avatar";
import { BigNum } from "@/components/ds/typography";
import { Chip } from "@/components/ds/chip";
import { Skeleton } from "@/components/ds/skeleton";
import { EmptyState } from "@/components/ds/empty-state";
import { PhoneList, PhoneListRow } from "@/components/ds/phone-row";
import { useIsPhone } from "@/lib/use-is-phone";

/**
 * All-coaches payslip overview for one month, read from the same monthly
 * payroll list as the Payroll tab (L7), so a coach's figure and status here
 * always match their payout period.
 */
export function PayslipsPanel({ month }: { month: string }) {
  const coachesQuery = useQuery({
    queryKey: ["admin", "users", "coach"],
    queryFn: () => listAdminUsers("coach"),
  });
  const payrollQuery = useQuery({
    queryKey: ["admin", "payroll", month],
    queryFn: () => listMonthlyPayroll(month),
  });

  const payrollRows = payrollQuery.data?.rows ?? [];
  const coaches = coachesQuery.data?.users ?? [];
  const rows = coaches.map((coach) => {
    const payrollRow = payrollRows.find((row) => row.coach_id === coach.user_id) ?? null;
    return {
      coach,
      sessions: payrollRow?.session_count ?? 0,
      netEarningsCents: payrollRow?.total_amount_cents ?? 0,
      chip: payslipChipFor(payrollRow?.status ?? "not_generated"),
    };
  });

  const loading = coachesQuery.isLoading || payrollQuery.isLoading;
  const error = coachesQuery.isError || payrollQuery.isError;

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
        <PayslipRows rows={rows} />
      )}
    </section>
  );
}

type PayslipRow = {
  coach: { user_id: string; display_name: string; email: string };
  sessions: number;
  netEarningsCents: number;
  chip: ReturnType<typeof payslipChipFor>;
};

/**
 * #857: each payslip was a 10rem card in a three-up grid, so on a phone one
 * coach filled most of the screen and scanning a dozen meant a dozen swipes.
 * Below `md` the same numbers render as the shared two-line row — net earnings
 * in line 1's primary slot, because that is the figure being checked.
 */
function PayslipRows({ rows }: { rows: PayslipRow[] }) {
  const isPhone = useIsPhone();
  if (isPhone) {
    return (
      <PhoneList aria-label="Coach payslips" data-testid="admin-coach-payslip-phone-list">
        {rows.map((row) => {
          const name = row.coach.display_name || row.coach.email;
          return (
            <PhoneListRow
              key={row.coach.user_id}
              data-testid={`admin-coach-payslip-row-${row.coach.user_id}`}
              leading={<Avatar name={name || "Coach"} size={32} />}
              title={name}
              primary={
                <span className="font-mono text-sm font-semibold tabular-nums text-rally-base">
                  {money(row.netEarningsCents)}
                </span>
              }
              secondary={
                <>
                  <div>
                    <Chip variant={row.chip.variant} label={row.chip.label} />
                  </div>
                  <div className="break-words">{row.coach.email}</div>
                  <div>
                    {row.sessions} class date{row.sessions === 1 ? "" : "s"}
                  </div>
                </>
              }
            />
          );
        })}
      </PhoneList>
    );
  }
  return (
    <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
          {rows.map((row) => (
            <Card key={row.coach.user_id} p={20} className="flex flex-col gap-4">
              <div className="flex items-center justify-between">
                <div className="flex items-center gap-3 truncate">
                  <Avatar name={row.coach.display_name || row.coach.email || "Coach"} />
                  <div className="truncate">
                    <div className="font-semibold leading-tight truncate">{row.coach.display_name || row.coach.email}</div>
                    <div className="text-xs text-neutral-500 truncate">
                      {row.coach.email} · {row.sessions} class date{row.sessions === 1 ? "" : "s"}
                    </div>
                  </div>
                </div>
                <div className="shrink-0 pl-2">
                  <Chip variant={row.chip.variant} label={row.chip.label} />
                </div>
              </div>

              <div className="mt-2 flex-1">
                <p className="text-xs font-medium uppercase tracking-wide text-neutral-500 mb-1">Net Earnings</p>
                <BigNum size={32}>
                  {money(row.netEarningsCents)}
                </BigNum>
              </div>

              <div className="flex flex-col gap-1 border-t border-neutral-100 pt-3 dark:border-neutral-800 text-sm">
                <div className="flex justify-between items-center">
                  <span className="text-neutral-500">Class dates</span>
                  <span className="font-mono font-medium">{row.sessions}</span>
                </div>
              </div>
            </Card>
          ))}
    </div>
  );
}
