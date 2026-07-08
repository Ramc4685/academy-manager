"use client";

import { Fragment, useState } from "react";
import { useMutation, useQuery } from "@tanstack/react-query";

import { exportAdminReportCsv, getAdminDepositSlip } from "@/lib/api/admin";
import { Card } from "@/components/ds/card";
import { Button } from "@/components/ds/button";
import { BigNum, Overline } from "@/components/ds/typography";

export default function AdminDepositSlipPage() {
  const [period, setPeriod] = useState(() => currentPeriod());

  const reportQuery = useQuery({
    queryKey: ["admin", "reports", "deposit-slip", period],
    queryFn: () => getAdminDepositSlip(period),
  });

  const exportMutation = useMutation({
    mutationFn: () => exportAdminReportCsv("deposit-slip", period),
    onSuccess: (csv) => downloadCsv(`deposit-slip-${period}`, csv),
  });

  const report = reportQuery.data;

  return (
    <section data-testid="admin-deposit-slip" className="space-y-5">
      <div className="flex flex-col gap-3 sm:flex-row sm:items-end sm:justify-between">
        <div>
          <Overline>Deposit slip</Overline>
          <p className="mt-1 text-sm text-rally-subtle">
            Gross payments received by day and method, for reconciling bank deposits.
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
          <Overline>Received</Overline>
          <BigNum size={28}>
            {report ? formatCurrency(report.total_cents) : reportQuery.isLoading ? "Loading" : "No data"}
          </BigNum>
          <p className="mt-2 text-[12px] text-rally-muted">
            Gross payments received in {formatMonth(period)}; refunds are not netted out.
          </p>
        </Card>
        <Card p={20} className="flex flex-col">
          <Overline>Payments</Overline>
          <BigNum size={28}>
            {report ? String(report.count) : reportQuery.isLoading ? "Loading" : "No data"}
          </BigNum>
          <p className="mt-2 text-[12px] text-rally-muted">Individual payments across all methods.</p>
        </Card>
      </div>

      {reportQuery.isError && (
        <p role="alert" className="rounded-md bg-red-50 p-3 text-sm text-red-700">
          Could not load the deposit slip.
        </p>
      )}
      {exportMutation.isError && (
        <p role="alert" className="rounded-md bg-red-50 p-3 text-sm text-red-700">
          Could not export the deposit slip.
        </p>
      )}

      <Card p={24}>
        <Overline>Daily deposits</Overline>
        {report?.days.length ? (
          <div className="mt-4 overflow-x-auto">
            <table className="w-full min-w-[480px] text-left text-sm">
              <thead className="text-xs uppercase text-rally-muted">
                <tr>
                  <th className="px-2 py-2">Date</th>
                  <th className="px-2 py-2">Method</th>
                  <th className="px-2 py-2">Payments</th>
                  <th className="px-2 py-2">Amount</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-rally-line">
                {report.days.map((day) => (
                  <Fragment key={day.date}>
                    {day.methods.map((method, index) => (
                      <tr key={`${day.date}-${method.method}`}>
                        <td className="px-2 py-2 font-medium text-rally-ink">
                          {index === 0 ? formatDay(day.date) : ""}
                        </td>
                        <td className="px-2 py-2 text-rally-muted">{method.method}</td>
                        <td className="px-2 py-2 text-rally-muted">{method.count}</td>
                        <td className="px-2 py-2 text-rally-muted">{formatCurrency(method.amount_cents)}</td>
                      </tr>
                    ))}
                    <tr className="bg-neutral-50 dark:bg-neutral-900">
                      <td className="px-2 py-2 text-xs uppercase text-rally-muted">Day total</td>
                      <td className="px-2 py-2" />
                      <td className="px-2 py-2 font-medium text-rally-ink">{day.count}</td>
                      <td className="px-2 py-2 font-medium text-rally-ink">{formatCurrency(day.total_cents)}</td>
                    </tr>
                  </Fragment>
                ))}
              </tbody>
            </table>
          </div>
        ) : (
          <p className="mt-3 text-sm text-rally-subtle">
            {reportQuery.isLoading ? "Loading deposits..." : "No payments received this month."}
          </p>
        )}
      </Card>
    </section>
  );
}

function formatCurrency(cents: number) {
  return new Intl.NumberFormat("en-US", { style: "currency", currency: "USD" }).format(cents / 100);
}

function formatDay(value: string) {
  const parsed = new Date(`${value}T00:00:00`);
  if (Number.isNaN(parsed.getTime())) return value;
  return new Intl.DateTimeFormat("en-US", { weekday: "short", month: "short", day: "numeric" }).format(parsed);
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
