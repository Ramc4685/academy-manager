"use client";

import { useState } from "react";
import { useMutation, useQuery } from "@tanstack/react-query";

import { exportAdminReportCsv, getAdminRefundsReport } from "@/lib/api/admin";
import { Card } from "@/components/ds/card";
import { Button } from "@/components/ds/button";
import { BigNum, Overline } from "@/components/ds/typography";

export default function AdminRefundsReportPage() {
  const [period, setPeriod] = useState(() => currentPeriod());

  const reportQuery = useQuery({
    queryKey: ["admin", "reports", "refunds", period],
    queryFn: () => getAdminRefundsReport(period),
  });

  const exportMutation = useMutation({
    mutationFn: () => exportAdminReportCsv("refunds", period),
    onSuccess: (csv) => downloadCsv(`refunds-${period}`, csv),
  });

  const report = reportQuery.data;

  return (
    <section data-testid="admin-refunds-report" className="space-y-5">
      <div className="flex flex-col gap-3 sm:flex-row sm:items-end sm:justify-between">
        <div>
          <Overline>Refunds &amp; credits</Overline>
          <p className="mt-1 text-sm text-rally-subtle">
            Money returned to families and account credits issued in the selected month.
          </p>
        </div>
        <div className="flex items-end gap-3">
          <label className="flex flex-col gap-1 text-sm font-medium text-rally-ink">
            Month
            <input
              type="month"
              value={period}
              onChange={(event) => setPeriod(event.target.value || currentPeriod())}
              className="h-10 rounded-md border border-rally-line bg-white px-3 text-sm text-rally-ink shadow-sm focus:border-rally-accent focus:outline-none focus:ring-2 focus:ring-rally-accent/20 dark:bg-neutral-950"
            />
          </label>
          <Button
            variant="secondary"
            onClick={() => exportMutation.mutate()}
            disabled={exportMutation.isPending}
          >
            {exportMutation.isPending ? "Exporting..." : "Export CSV"}
          </Button>
        </div>
      </div>

      <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
        <StatCard
          label="Refunded"
          value={report ? formatCurrency(report.total_refunded_cents) : loadingValue(reportQuery.isLoading)}
        />
        <StatCard label="Refunds" value={report ? String(report.refund_count) : loadingValue(reportQuery.isLoading)} />
        <StatCard
          label="Credits issued"
          value={report ? formatCurrency(report.total_credit_cents) : loadingValue(reportQuery.isLoading)}
        />
        <StatCard label="Credit entries" value={report ? String(report.credit_count) : loadingValue(reportQuery.isLoading)} />
      </div>

      {reportQuery.isError && (
        <p role="alert" className="rounded-md bg-red-50 p-3 text-sm text-red-700">
          Could not load the refunds report.
        </p>
      )}
      {exportMutation.isError && (
        <p role="alert" className="rounded-md bg-red-50 p-3 text-sm text-red-700">
          Could not export the refunds report.
        </p>
      )}

      <Card p={24}>
        <Overline>Refunds</Overline>
        {report?.refunds.length ? (
          <div className="mt-4 overflow-x-auto">
            <table className="w-full min-w-[640px] text-left text-sm">
              <thead className="text-xs uppercase text-rally-muted">
                <tr>
                  <th className="px-2 py-2">Date</th>
                  <th className="px-2 py-2">Invoice</th>
                  <th className="px-2 py-2">Parent</th>
                  <th className="px-2 py-2">Amount</th>
                  <th className="px-2 py-2">Reason</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-rally-line">
                {report.refunds.map((row, index) => (
                  <tr key={`${row.invoice_id ?? "refund"}-${index}`}>
                    <td className="px-2 py-2 text-rally-muted">{formatDate(row.refund_at)}</td>
                    <td className="px-2 py-2 font-medium text-rally-ink">
                      {row.invoice_number ?? row.invoice_id ?? "—"}
                    </td>
                    <td className="px-2 py-2 text-rally-muted">{row.parent_id ?? "—"}</td>
                    <td className="px-2 py-2 font-medium text-rally-ink">{formatCurrency(row.amount_cents)}</td>
                    <td className="px-2 py-2 text-rally-muted">{row.reason ?? "—"}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        ) : (
          <p className="mt-3 text-sm text-rally-subtle">
            {reportQuery.isLoading ? "Loading refunds..." : "No refunds issued this month."}
          </p>
        )}
      </Card>

      <Card p={24}>
        <Overline>Account credits</Overline>
        {report?.credits.length ? (
          <div className="mt-4 overflow-x-auto">
            <table className="w-full min-w-[640px] text-left text-sm">
              <thead className="text-xs uppercase text-rally-muted">
                <tr>
                  <th className="px-2 py-2">Date</th>
                  <th className="px-2 py-2">Type</th>
                  <th className="px-2 py-2">Status</th>
                  <th className="px-2 py-2">Parent</th>
                  <th className="px-2 py-2">Amount</th>
                  <th className="px-2 py-2">Remaining</th>
                  <th className="px-2 py-2">Reason</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-rally-line">
                {report.credits.map((row) => (
                  <tr key={row.credit_id}>
                    <td className="px-2 py-2 text-rally-muted">{formatDate(row.created_at)}</td>
                    <td className="px-2 py-2 font-medium text-rally-ink">{row.type ?? "—"}</td>
                    <td className="px-2 py-2 text-rally-muted">{row.status ?? "—"}</td>
                    <td className="px-2 py-2 text-rally-muted">{row.parent_id ?? "—"}</td>
                    <td className="px-2 py-2 font-medium text-rally-ink">{formatCurrency(row.amount_cents)}</td>
                    <td className="px-2 py-2 text-rally-muted">{formatCurrency(row.remaining_amount_cents)}</td>
                    <td className="px-2 py-2 text-rally-muted">{row.reason ?? "—"}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        ) : (
          <p className="mt-3 text-sm text-rally-subtle">
            {reportQuery.isLoading ? "Loading credits..." : "No account credits issued this month."}
          </p>
        )}
      </Card>
    </section>
  );
}

function StatCard({ label, value }: { label: string; value: string }) {
  return (
    <Card p={20} className="flex flex-col">
      <Overline>{label}</Overline>
      <BigNum size={28}>{value}</BigNum>
    </Card>
  );
}

function loadingValue(isLoading: boolean): string {
  return isLoading ? "Loading" : "No data";
}

function formatCurrency(cents: number) {
  return new Intl.NumberFormat("en-US", { style: "currency", currency: "USD" }).format(cents / 100);
}

function formatDate(value: string | null) {
  if (!value) return "—";
  const parsed = new Date(value);
  if (Number.isNaN(parsed.getTime())) return value;
  return new Intl.DateTimeFormat("en-US", { dateStyle: "medium" }).format(parsed);
}

function currentPeriod() {
  const now = new Date();
  return `${now.getFullYear()}-${String(now.getMonth() + 1).padStart(2, "0")}`;
}

function downloadCsv(title: string, csv: string) {
  const blob = new Blob([csv], { type: "text/csv;charset=utf-8" });
  const url = URL.createObjectURL(blob);
  const anchor = document.createElement("a");
  anchor.href = url;
  anchor.download = `${title}.csv`;
  anchor.click();
  URL.revokeObjectURL(url);
}
