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
import { generatePayoutPeriod } from "@/lib/api/v2/payouts";
import { rowHasUnresolvedWarnings } from "@/lib/payroll-warnings";
import { ConfirmActionDialog } from "@/components/ds/confirm-action-dialog";
import { EmptyState } from "@/components/ds/empty-state";
import { MonthPicker } from "./_components/MonthPicker";
import { PayslipsPanel } from "./_components/PayslipsPanel";
import { PayrollRows } from "./_components/PayrollRows";
import { useAcademyTimezone } from "@/components/admin/use-academy-today";
import { academyMonthKey } from "@/lib/format/academy-time";

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
  const timezone = useAcademyTimezone();
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

  const [month, setMonth] = useState(() => academyMonthKey(timezone));
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
  // Coaches who taught nothing are listed but never get a payslip.
  const payableCount = rows.filter((row) => row.generatable !== false).length;
  const warningRows = rows.filter(
    (row) => rowHasUnresolvedWarnings(row) || (row.unresolved_unpaid_count ?? 0) > 0,
  );

  return (
    <div className="space-y-4 p-6" data-testid="admin-payouts">
      <div className="flex items-center justify-between">
        <h1 className="text-xl font-semibold">Coach Payroll</h1>
        <MonthPicker value={month} onChange={setMonth} />
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
          <PayslipsPanel month={month} />
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

            {generateOne.isError || bulkGenerate.isError || bulkRecompute.isError ? (
              <p
                role="alert"
                data-testid="admin-payroll-generate-error"
                className="rounded-lg border border-status-red-200 bg-status-red-50 px-4 py-3 text-sm text-status-red-800"
              >
                Payroll could not be generated. Nothing was saved; try again, and if it keeps
                failing, contact support.
              </p>
            ) : null}
            <p className="text-sm text-muted-foreground">
              Every active coach is listed. A coach who taught no classes this month has nothing to
              generate.
            </p>

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
        subject={`${month} · ${payableCount === 1 ? "1 coach" : `${payableCount} coaches`}`}
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
        subject={`${month} · ${payableCount === 1 ? "1 coach" : `${payableCount} coaches`}`}
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
