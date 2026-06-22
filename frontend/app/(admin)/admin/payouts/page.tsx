"use client";
import { useState } from "react";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { useRouter } from "next/navigation";
import {
  listMonthlyPayroll,
  generateMonthlyPayroll,
  recomputeMonthlyPayroll,
  exportMonthlyPayrollXlsx,
} from "@/lib/api/v2/payroll";
import { generatePayoutPeriod } from "@/lib/api/v2/payouts";
import { rowHasUnresolvedWarnings } from "@/lib/payroll-warnings";
import { MonthPicker } from "./_components/MonthPicker";

export default function PayoutsPage() {
  const router = useRouter();
  const qc = useQueryClient();
  const [month, setMonth] = useState(() => new Date().toISOString().slice(0, 7));

  const { data, isLoading } = useQuery({
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
  const warningRows = rows.filter(rowHasUnresolvedWarnings);

  return (
    <div className="space-y-4 p-6" data-testid="admin-payouts">
      <div className="flex items-center justify-between">
        <h1 className="text-xl font-semibold">Coach Payroll</h1>
        <MonthPicker value={month} onChange={setMonth} />
      </div>

      {warningRows.length > 0 && (
        <div className="rounded-md border border-yellow-300 bg-yellow-50 px-4 py-3 text-sm text-yellow-800">
          <strong>
            {warningRows.length} coach{warningRows.length > 1 ? "es" : ""}
          </strong>{" "}
          have unresolved payout warnings. Open each payout, repair the session fee or coach
          rate, then recompute before approval.
        </div>
      )}

      <div className="flex gap-2">
        <button
          className="rounded border px-3 py-1.5 text-sm disabled:opacity-50"
          disabled={bulkGenerate.isPending}
          onClick={() => bulkGenerate.mutate()}
        >
          Generate all
        </button>
        <button
          className="rounded border px-3 py-1.5 text-sm disabled:opacity-50"
          disabled={bulkRecompute.isPending}
          onClick={() => bulkRecompute.mutate()}
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

      {isLoading ? (
        <p className="text-sm text-muted-foreground">Loading…</p>
      ) : (
        <table className="w-full text-sm border-collapse">
          <thead>
            <tr className="border-b text-left text-muted-foreground">
              <th className="py-2 pr-4 font-medium">Coach</th>
              <th className="py-2 pr-4 font-medium">Sessions</th>
              <th className="py-2 pr-4 font-medium">Total</th>
              <th className="py-2 pr-4 font-medium">Warnings</th>
              <th className="py-2 pr-4 font-medium">Status</th>
              <th className="py-2 font-medium" />
            </tr>
          </thead>
          <tbody>
            {rows.map((row) => (
              <tr key={row.coach_id} className="border-b hover:bg-muted/30">
                <td className="py-2 pr-4">{row.coach_name ?? row.coach_id}</td>
                <td className="py-2 pr-4">{row.session_count}</td>
                <td className="py-2 pr-4">
                  {(row.total_amount_cents / 100).toFixed(2)} {row.currency}
                </td>
                <td className="py-2 pr-4">
                  {row.warning_count > 0 ? (
                    <span className="rounded bg-amber-100 px-2 py-0.5 text-xs font-medium text-amber-800">
                      {row.warning_count} unresolved
                    </span>
                  ) : (
                    <span className="text-xs text-muted-foreground">Clear</span>
                  )}
                </td>
                <td className="py-2 pr-4">
                  <StatusChip status={row.status} />
                </td>
                <td className="py-2">
                  {row.period_id ? (
                    <a
                      href={`/admin/payouts/${row.period_id}`}
                      className="text-primary underline"
                    >
                      Open
                    </a>
                  ) : (
                    <button
                      className="text-primary underline disabled:opacity-50"
                      disabled={generateOne.isPending}
                      onClick={() =>
                        generateOne.mutate({
                          coach_id: row.coach_id,
                          period_start: data!.period_start,
                          period_end: data!.period_end,
                        })
                      }
                    >
                      Generate
                    </button>
                  )}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </div>
  );
}

function StatusChip({ status }: { status: string }) {
  const map: Record<string, { label: string; cls: string }> = {
    not_generated: { label: "Not generated", cls: "bg-gray-100 text-gray-600" },
    draft: { label: "Draft", cls: "bg-blue-100 text-blue-700" },
    approved: { label: "Approved", cls: "bg-yellow-100 text-yellow-700" },
    paid: { label: "Paid", cls: "bg-green-100 text-green-700" },
  };
  const { label, cls } = map[status] ?? { label: status, cls: "" };
  return (
    <span className={`rounded px-2 py-0.5 text-xs font-medium ${cls}`}>{label}</span>
  );
}
