"use client";

import type { Route } from "next";

import type { AdminMonthlyPayrollRow, MonthlyPayrollStatus } from "@/lib/api/v2/payroll";
import { payslipChipFor } from "@/lib/payslip-chip";
import { money } from "@/lib/format-money";
import { Chip } from "@/components/ds/chip";
import { PhoneList, PhoneListRow } from "@/components/ds/phone-row";
import { useIsPhone } from "@/lib/use-is-phone";

/**
 * #857: the payroll table's seven columns put Total, Status and the
 * Open/Generate link off a phone screen, which is the whole row. The desktop
 * DS table from #845 is untouched; below `md` the same values render as the
 * shared two-line phone row (`lib/use-is-phone.ts` mounts exactly one).
 */
/** D-04: an active coach with no classes this month is listed, muted, with nothing to generate. */
export const NO_CLASSES_NOTE = "No classes taught yet";

function taughtNothing(row: AdminMonthlyPayrollRow): boolean {
  return row.generatable === false;
}

export function PayrollRows({
  rows,
  periodStart,
  periodEnd,
  generatePending,
  onGenerate,
}: {
  rows: AdminMonthlyPayrollRow[];
  periodStart: string | null;
  periodEnd: string | null;
  generatePending: boolean;
  onGenerate: (input: { coach_id: string; period_start: string; period_end: string }) => void;
}) {
  const isPhone = useIsPhone();

  function generate(coachId: string) {
    if (!periodStart || !periodEnd) return;
    onGenerate({ coach_id: coachId, period_start: periodStart, period_end: periodEnd });
  }

  if (isPhone) {
    return (
      <PhoneList aria-label="Payroll" data-testid="admin-payroll-phone-list">
        {rows.map((row) => {
          const name = row.coach_name ?? row.coach_id;
          return (
            <PhoneListRow
              key={row.coach_id}
              data-testid={`admin-payroll-row-${row.coach_id}`}
              title={name}
              primary={
                <span className="font-mono text-sm font-semibold tabular-nums text-rally-base">
                  {money(row.total_amount_cents)}
                </span>
              }
              actionsLabel={`Actions for ${name}`}
              actionsTestId={`admin-payroll-actions-${row.coach_id}`}
              actions={
                taughtNothing(row)
                  ? []
                  : row.period_id
                  ? [
                      {
                        key: "open",
                        label: "Open",
                        href: `/admin/payouts/${row.period_id}` as Route,
                      },
                    ]
                  : [
                      {
                        key: "generate",
                        label: "Generate",
                        disabled: generatePending || !periodStart || !periodEnd,
                        onSelect: () => generate(row.coach_id),
                      },
                    ]
              }
              secondary={
                taughtNothing(row) ? (
                  <span className="text-rally-muted">{NO_CLASSES_NOTE}</span>
                ) : (
                <>
                  <div className="flex flex-wrap items-center gap-2">
                    <PayrollStatusChip status={row.status} />
                    {row.warning_count > 0 ? (
                      <Chip variant="approval" label={`${row.warning_count} unresolved`} />
                    ) : (
                      <span className="text-xs text-rally-muted">Clear</span>
                    )}
                  </div>
                  <div>
                    {row.session_count} {row.session_count === 1 ? "session" : "sessions"}
                    {row.unresolved_unpaid_count > 0
                      ? ` · ${row.unresolved_unpaid_count} unpaid unresolved`
                      : ""}
                  </div>
                </>
                )
              }
            />
          );
        })}
      </PhoneList>
    );
  }

  return (
    <div className="overflow-x-auto">
      <table className="w-full text-sm border-collapse">
        <thead>
          <tr className="border-b text-left text-muted-foreground">
            <th className="py-2 pr-4 font-medium">Coach</th>
            <th className="py-2 pr-4 font-medium">Sessions</th>
            <th className="py-2 pr-4 font-medium">Unpaid</th>
            <th className="py-2 pr-4 font-medium">Total</th>
            <th className="py-2 pr-4 font-medium">Warnings</th>
            <th className="py-2 pr-4 font-medium">Status</th>
            <th className="py-2 font-medium" />
          </tr>
        </thead>
        <tbody>
          {rows.map((row) =>
            taughtNothing(row) ? (
              <tr
                key={row.coach_id}
                data-testid={`admin-payroll-row-${row.coach_id}`}
                data-muted="true"
                className="border-b text-rally-muted"
              >
                <td className="py-2 pr-4">{row.coach_name ?? row.coach_id}</td>
                <td className="py-2 pr-4" colSpan={6}>
                  {NO_CLASSES_NOTE}
                </td>
              </tr>
            ) : (
            <tr
              key={row.coach_id}
              data-testid={`admin-payroll-row-${row.coach_id}`}
              className="border-b hover:bg-muted/30"
            >
              <td className="py-2 pr-4">{row.coach_name ?? row.coach_id}</td>
              <td className="py-2 pr-4">{row.session_count}</td>
              <td className="py-2 pr-4">
                {row.unresolved_unpaid_count > 0 ? (
                  <Chip variant="approval" label={`${row.unresolved_unpaid_count} unresolved`} />
                ) : (
                  "0"
                )}
              </td>
              <td className="py-2 pr-4">{money(row.total_amount_cents)}</td>
              <td className="py-2 pr-4">
                {row.warning_count > 0 ? (
                  <Chip variant="approval" label={`${row.warning_count} unresolved`} />
                ) : (
                  <span className="text-xs text-rally-muted">Clear</span>
                )}
              </td>
              <td className="py-2 pr-4">
                <PayrollStatusChip status={row.status} />
              </td>
              <td className="py-2">
                {row.period_id ? (
                  <a href={`/admin/payouts/${row.period_id}`} className="text-primary underline">
                    Open
                  </a>
                ) : (
                  <button
                    className="text-primary underline disabled:opacity-50"
                    disabled={generatePending || !periodStart || !periodEnd}
                    onClick={() => generate(row.coach_id)}
                  >
                    Generate
                  </button>
                )}
              </td>
            </tr>
            ),
          )}
        </tbody>
      </table>
    </div>
  );
}

function PayrollStatusChip({ status }: { status: MonthlyPayrollStatus }) {
  const chip = payslipChipFor(status);
  return <Chip variant={chip.variant} label={chip.label} />;
}
