"use client";
import { Suspense, useState } from "react";
import type { KeyboardEvent } from "react";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { useRouter, useSearchParams } from "next/navigation";
import {
  listMonthlyPayroll,
  generateMonthlyPayroll,
  recomputeMonthlyPayroll,
  exportMonthlyPayrollXlsx,
} from "@/lib/api/v2/payroll";
import type { AdminMonthlyPayrollRow, MonthlyPayrollStatus } from "@/lib/api/v2/payroll";
import type { Route } from "next";
import { generatePayoutPeriod } from "@/lib/api/v2/payouts";
import { rowHasUnresolvedWarnings } from "@/lib/payroll-warnings";
import { payslipChipFor } from "@/lib/payslip-chip";
import { money } from "@/lib/format-money";
import { ConfirmActionDialog } from "@/components/admin/confirm-action-dialog";
import { Chip } from "@/components/ds/chip";
import { EmptyState } from "@/components/ds/empty-state";
import { PhoneList, PhoneListRow } from "@/components/ds/phone-row";
import { useIsPhone } from "@/lib/use-is-phone";
import { MonthPicker } from "./_components/MonthPicker";
import { PayslipsPanel } from "./_components/PayslipsPanel";

/** #838: the two batch payroll actions that used to run on a single click. */
type BulkAction = "generate" | "recompute";

type PayoutsTab = "payroll" | "payslips";

const TABS: { id: PayoutsTab; label: string }[] = [
  { id: "payroll", label: "Payroll" },
  { id: "payslips", label: "Payslips" },
];

export default function PayoutsPage() {
  return (
    <Suspense
      fallback={<div className="p-6 text-sm text-muted-foreground">Loading...</div>}
    >
      <PayoutsContent />
    </Suspense>
  );
}

function PayoutsContent() {
  const router = useRouter();
  const searchParams = useSearchParams();
  const qc = useQueryClient();
  const tab: PayoutsTab = searchParams.get("tab") === "payslips" ? "payslips" : "payroll";

  function selectTab(next: PayoutsTab) {
    router.replace(next === "payslips" ? "/admin/payouts?tab=payslips" : "/admin/payouts");
  }

  function focusTab(next: PayoutsTab) {
    document.getElementById(`payouts-tab-${next}`)?.focus();
  }

  function handleTabKeyDown(event: KeyboardEvent<HTMLButtonElement>, current: PayoutsTab) {
    if (event.key !== "ArrowRight" && event.key !== "ArrowLeft") {
      return;
    }
    event.preventDefault();
    const currentIndex = TABS.findIndex((candidate) => candidate.id === current);
    const offset = event.key === "ArrowRight" ? 1 : -1;
    const next = TABS[(currentIndex + offset + TABS.length) % TABS.length].id;
    focusTab(next);
    selectTab(next);
  }

  const [month, setMonth] = useState(() => new Date().toISOString().slice(0, 7));
  const [bulkConfirm, setBulkConfirm] = useState<BulkAction | null>(null);

  const { data, isLoading, isError } = useQuery({
    queryKey: ["admin", "payroll", month],
    queryFn: () => listMonthlyPayroll(month),
  });

  const generateOne = useMutation({
    mutationFn: (args: { coach_id: string; period_start: string; period_end: string }) =>
      generatePayoutPeriod(args),
    onSuccess: (period) => {
      qc.invalidateQueries({ queryKey: ["admin", "payroll", month] });
      router.push(`/admin/payouts/${period.period_id}`);
    },
  });
  const bulkGenerate = useMutation({
    mutationFn: () => generateMonthlyPayroll(month),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["admin", "payroll", month] }),
  });
  const bulkRecompute = useMutation({
    mutationFn: () => recomputeMonthlyPayroll(month),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["admin", "payroll", month] }),
  });
  const bulkExport = useMutation({
    mutationFn: () => exportMonthlyPayrollXlsx(month),
    onSuccess: (blob) => {
      const url = URL.createObjectURL(blob);
      const a = document.createElement("a");
      a.href = url;
      a.download = `payroll-${month}.xlsx`;
      a.click();
      URL.revokeObjectURL(url);
    },
  });

  const rows = data?.rows ?? [];
  const warningRows = rows.filter(
    (row) => rowHasUnresolvedWarnings(row) || (row.unresolved_unpaid_count ?? 0) > 0,
  );

  return (
    <div className="space-y-4 p-6" data-testid="admin-payouts">
      <div className="flex items-center justify-between">
        <h1 className="text-xl font-semibold">Coach Payroll</h1>
        {tab === "payroll" && <MonthPicker value={month} onChange={setMonth} />}
      </div>

      <div
        role="tablist"
        aria-label="Payouts view"
        className="flex flex-wrap gap-1 rounded-xl bg-neutral-100 p-1 dark:bg-neutral-800"
      >
        {TABS.map((t) => (
          <button
            key={t.id}
            id={`payouts-tab-${t.id}`}
            type="button"
            role="tab"
            aria-selected={tab === t.id}
            aria-controls={`payouts-panel-${t.id}`}
            tabIndex={tab === t.id ? 0 : -1}
            onClick={() => selectTab(t.id)}
            onKeyDown={(event) => handleTabKeyDown(event, t.id)}
            className="min-h-touch flex-1 rounded-lg px-3 text-sm font-semibold transition-all duration-150"
            style={
              tab === t.id
                ? {
                    background: "white",
                    color: "var(--rally-ink)",
                    boxShadow: "0 1px 2px rgba(0,0,0,0.06)",
                  }
                : { background: "transparent", color: "var(--rally-muted)" }
            }
          >
            {t.label}
          </button>
        ))}
      </div>

      <div
        id={`payouts-panel-${tab}`}
        role="tabpanel"
        aria-labelledby={`payouts-tab-${tab}`}
        tabIndex={0}
      >
        {tab === "payslips" ? (
          <PayslipsPanel />
        ) : (
          <>
            {warningRows.length > 0 && (
              <div className="rounded-md border border-yellow-300 bg-yellow-50 px-4 py-3 text-sm text-yellow-800">
                <strong>
                  {warningRows.length} coach{warningRows.length > 1 ? "es" : ""}
                </strong>{" "}
                have unresolved payroll warnings or unpaid occurrences. Open each payout, repair the
                session fee or coach rate, then recompute before approval.
              </div>
            )}

            <div className="flex gap-2">
              <button
                className="rounded border px-3 py-1.5 text-sm disabled:opacity-50"
                disabled={bulkGenerate.isPending}
                onClick={() => setBulkConfirm("generate")}
              >
                Generate all
              </button>
              <button
                className="rounded border px-3 py-1.5 text-sm disabled:opacity-50"
                disabled={bulkRecompute.isPending}
                onClick={() => setBulkConfirm("recompute")}
              >
                Recompute all
              </button>
              <button
                className="rounded border px-3 py-1.5 text-sm disabled:opacity-50"
                disabled={bulkExport.isPending}
                onClick={() => bulkExport.mutate()}
              >
                Export month
              </button>
            </div>

            {isError ? (
              <div role="alert">
                <EmptyState
                  data-testid="admin-payroll-error"
                  title="Could not load payroll for this month."
                  compact
                />
              </div>
            ) : isLoading ? (
              <p className="text-sm text-muted-foreground">Loading…</p>
            ) : (
              <PayrollRows
                rows={rows}
                periodStart={data?.period_start ?? null}
                periodEnd={data?.period_end ?? null}
                generatePending={generateOne.isPending}
                onGenerate={(input) => generateOne.mutate(input)}
              />
            )}
          </>
        )}
      </div>

      <ConfirmActionDialog
        open={bulkConfirm === "generate"}
        onOpenChange={(open) => !open && setBulkConfirm(null)}
        overline="Generate payroll"
        title="Generate payslips for every coach?"
        subject={`${month} · ${rows.length === 1 ? "1 coach" : `${rows.length} coaches`}`}
        consequence={
          <>
            <p>
              Creates a draft payslip for each coach who does not already have one this month.
              Coaches are not paid and are not emailed — drafts still need approval.
            </p>
            {warningRows.length > 0 && (
              <p>
                {warningRows.length === 1 ? "1 coach has" : `${warningRows.length} coaches have`}{" "}
                unresolved payroll warnings. Generating now bakes the current, possibly wrong,
                session fee or coach rate into the draft.
              </p>
            )}
          </>
        }
        confirmLabel="Generate all"
        confirmVariant="primary"
        pending={bulkGenerate.isPending}
        onConfirm={() => {
          bulkGenerate.mutate();
          setBulkConfirm(null);
        }}
      />

      <ConfirmActionDialog
        open={bulkConfirm === "recompute"}
        onOpenChange={(open) => !open && setBulkConfirm(null)}
        overline="Recompute payroll"
        title="Recompute every draft payslip?"
        subject={`${month} · ${rows.length === 1 ? "1 coach" : `${rows.length} coaches`}`}
        consequence={
          <>
            <p>
              Rebuilds each draft from the current session fees, coach rates and attendance, so
              amounts already reviewed this month can change. Approved and paid payslips are left
              alone; nobody is paid and nobody is emailed.
            </p>
          </>
        }
        confirmLabel="Recompute all"
        pending={bulkRecompute.isPending}
        onConfirm={() => {
          bulkRecompute.mutate();
          setBulkConfirm(null);
        }}
      />
    </div>
  );
}

/**
 * #857: the payroll table's seven columns put Total, Status and the
 * Open/Generate link off a phone screen, which is the whole row. The desktop
 * DS table from #845 is untouched; below `md` the same values render as the
 * shared two-line phone row (`lib/use-is-phone.ts` mounts exactly one).
 */
function PayrollRows({
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
                row.period_id
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
          {rows.map((row) => (
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
          ))}
        </tbody>
      </table>
    </div>
  );
}

function PayrollStatusChip({ status }: { status: MonthlyPayrollStatus }) {
  const chip = payslipChipFor(status, null);
  return <Chip variant={chip.variant} label={chip.label} />;
}
