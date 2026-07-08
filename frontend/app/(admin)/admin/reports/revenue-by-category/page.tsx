"use client";

import { useState } from "react";
import { useMutation, useQuery } from "@tanstack/react-query";

import { exportAdminReportCsv, getAdminRevenueByCategory } from "@/lib/api/admin";
import { Card } from "@/components/ds/card";
import { Button } from "@/components/ds/button";
import { BigNum, Overline } from "@/components/ds/typography";

export default function AdminRevenueByCategoryPage() {
  const [period, setPeriod] = useState(() => currentPeriod());

  const reportQuery = useQuery({
    queryKey: ["admin", "reports", "revenue-by-category", period],
    queryFn: () => getAdminRevenueByCategory(period),
  });

  const exportMutation = useMutation({
    mutationFn: () => exportAdminReportCsv("revenue-by-category", period),
    onSuccess: (csv) => downloadCsv(`revenue-by-category-${period}`, csv),
  });

  const report = reportQuery.data;
  const total = report?.total_allocated_cents ?? 0;

  return (
    <section data-testid="admin-revenue-by-category" className="space-y-5">
      <div className="flex flex-col gap-3 sm:flex-row sm:items-end sm:justify-between">
        <div>
          <Overline>Revenue by category</Overline>
          <p className="mt-1 text-sm text-rally-subtle">
            Cash collected in the month, split by the invoice line categories it paid for.
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

      <div className="grid gap-4 sm:grid-cols-2">
        <Card p={20} className="flex flex-col">
          <Overline>Collected &amp; applied</Overline>
          <BigNum size={28}>
            {report ? formatCurrency(report.total_allocated_cents) : reportQuery.isLoading ? "Loading" : "No data"}
          </BigNum>
          <p className="mt-2 text-[12px] text-rally-muted">
            Payments applied to invoices during {formatMonth(period)}.
          </p>
        </Card>
        <Card p={20} className="flex flex-col">
          <Overline>Unapplied payments</Overline>
          <BigNum size={28}>
            {report ? formatCurrency(report.unapplied_cents) : reportQuery.isLoading ? "Loading" : "No data"}
          </BigNum>
          <p className="mt-2 text-[12px] text-rally-muted">
            Money received this month not yet applied to an invoice.
          </p>
        </Card>
      </div>

      {reportQuery.isError && (
        <p role="alert" className="rounded-md bg-red-50 p-3 text-sm text-red-700">
          Could not load the revenue report.
        </p>
      )}
      {exportMutation.isError && (
        <p role="alert" className="rounded-md bg-red-50 p-3 text-sm text-red-700">
          Could not export the revenue report.
        </p>
      )}

      <Card p={24}>
        <Overline>Categories</Overline>
        {report?.rows.length ? (
          <div className="mt-4 overflow-x-auto">
            <table className="w-full min-w-[480px] text-left text-sm">
              <thead className="text-xs uppercase text-rally-muted">
                <tr>
                  <th className="px-2 py-2">Category</th>
                  <th className="px-2 py-2">Amount</th>
                  <th className="px-2 py-2">Share</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-rally-line">
                {report.rows.map((row) => (
                  <tr key={row.category}>
                    <td className="px-2 py-2 font-medium text-rally-ink">
                      {row.category_label ?? row.category}
                    </td>
                    <td className="px-2 py-2 text-rally-muted">{formatCurrency(row.amount_cents)}</td>
                    <td className="px-2 py-2 text-rally-muted">
                      {total > 0 ? formatPercent(row.amount_cents / total) : "—"}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        ) : (
          <p className="mt-3 text-sm text-rally-subtle">
            {reportQuery.isLoading ? "Loading revenue..." : "No payments were applied to invoices this month."}
          </p>
        )}
      </Card>
    </section>
  );
}

function formatCurrency(cents: number) {
  return new Intl.NumberFormat("en-US", { style: "currency", currency: "USD" }).format(cents / 100);
}

function formatPercent(value: number): string {
  return new Intl.NumberFormat("en-US", {
    style: "percent",
    maximumFractionDigits: 1,
  }).format(value);
}

function formatMonth(value: string) {
  const [year, month] = value.split("-").map(Number);
  if (!year || !month) return value;
  return new Intl.DateTimeFormat("en-US", { month: "short", year: "numeric" }).format(
    new Date(year, month - 1, 1),
  );
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
