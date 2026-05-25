"use client";

import { useState } from "react";
import { useMutation, useQuery } from "@tanstack/react-query";

import { exportAdminReportCsv, getAdminReportsDashboard, getRevenue } from "@/lib/api/admin";
import { Card } from "@/components/ds/card";
import { Button } from "@/components/ds/button";
import { MiniBars } from "@/components/ds/charts";
import { BigNum, Overline } from "@/components/ds/typography";

const REPORTS = [
  {
    name: "pending-payments",
    title: "Pending payments",
    description: "Invoices still waiting for payment.",
  },
  {
    name: "revenue",
    title: "Revenue",
    description: "Monthly collected revenue.",
  },
  {
    name: "attendance",
    title: "Attendance",
    description: "Recent attendance marks.",
  },
] as const;

export default function AdminReportsPage() {
  const [preview, setPreview] = useState<{ title: string; csv: string } | null>(null);
  const [period, setPeriod] = useState(() => currentPeriod());

  const revenueQuery = useQuery({
    queryKey: ["admin", "revenue"],
    queryFn: getRevenue,
  });

  const dashboardQuery = useQuery({
    queryKey: ["admin", "reports", "dashboard", period],
    queryFn: () => getAdminReportsDashboard(period),
  });

  const exportMutation = useMutation({
    mutationFn: async (report: (typeof REPORTS)[number]) => {
      const csv = await exportAdminReportCsv(report.name);
      return { title: report.title, csv };
    },
    onSuccess: (data) => {
      setPreview(data);
    },
  });

  const revenueByMonth = revenueQuery.data?.by_month ?? {};
  const sortedMonths = Object.keys(revenueByMonth).sort();
  const last6Months = sortedMonths.slice(-6);
  const chartValues = last6Months.map((month) => revenueByMonth[month]);
  const latestMonth = last6Months.at(-1);
  const latestRevenue = latestMonth ? revenueByMonth[latestMonth] : null;
  const sixMonthRevenue = chartValues.reduce((total, value) => total + value, 0);
  const dashboard = dashboardQuery.data;

  return (
    <section data-testid="admin-reports" className="space-y-5">
      <div className="space-y-3">
        <div className="flex flex-col gap-3 sm:flex-row sm:items-end sm:justify-between">
          <div>
            <Overline>Owner dashboard</Overline>
            <p className="mt-1 text-sm text-rally-subtle">
              Finance and operations for the selected month.
            </p>
          </div>
          <label className="flex flex-col gap-1 text-sm font-medium text-rally-ink">
            Month
            <input
              type="month"
              value={period}
              onChange={(event) => setPeriod(event.target.value || currentPeriod())}
              className="h-10 rounded-md border border-rally-line bg-white px-3 text-sm text-rally-ink shadow-sm focus:border-rally-accent focus:outline-none focus:ring-2 focus:ring-rally-accent/20 dark:bg-neutral-950"
            />
          </label>
        </div>
        <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
          <KpiCard
            label="Cash collected"
            value={dashboard ? formatCurrency(dashboard.cash_collected_cents) : dashboardQuery.isLoading ? "Loading" : "No data"}
            description="Recorded payments net of refunds for this period."
          />
          <KpiCard
            label="Outstanding dues"
            value={dashboard ? formatCurrency(dashboard.outstanding_dues_cents) : dashboardQuery.isLoading ? "Loading" : "No data"}
            description="Open or partially paid dues still requiring follow-up."
          />
          <KpiCard
            label="Attendance rate"
            value={dashboard ? formatNullablePercent(dashboard.attendance.attendance_rate) : dashboardQuery.isLoading ? "Loading" : "No data"}
            description="Present or late marks out of recorded attendance."
          />
          <KpiCard
            label="Capacity used"
            value={dashboard ? formatNullablePercent(dashboard.sessions.capacity_utilization) : dashboardQuery.isLoading ? "Loading" : "No data"}
            description="Enrolled seats against scheduled and completed capacity."
          />
          <KpiCard
            label="Net profit"
            value={dashboard ? formatNullableCurrency(dashboard.profit_and_loss.net_profit_cents) : dashboardQuery.isLoading ? "Loading" : "No data"}
            description="Revenue less expenses and available coach payroll."
          />
          <KpiCard
            label="Expenses"
            value={dashboard ? formatCurrency(dashboard.expenses.total_cents) : dashboardQuery.isLoading ? "Loading" : "No data"}
            description="Recorded rent, equipment, salary, marketing, and other spend."
          />
          <KpiCard
            label="Payroll unpaid"
            value={dashboard ? formatNullableCurrency(dashboard.payroll.unpaid_cents) : dashboardQuery.isLoading ? "Loading" : "No data"}
            description="Approved coach payout amount not yet marked paid."
          />
          <KpiCard
            label="Waitlist"
            value={dashboard ? formatInteger(dashboard.sessions.waitlist_count) : dashboardQuery.isLoading ? "Loading" : "No data"}
            description="Families waiting on sessions in the selected month."
          />
        </div>

        {dashboardQuery.isError && (
          <p role="alert" className="rounded-md bg-red-50 p-3 text-sm text-red-700">
            Could not load the reports dashboard.
          </p>
        )}

        {dashboard?.empty_states.length ? (
          <Card p={20}>
            <Overline>Empty states</Overline>
            <ul className="mt-3 space-y-2 text-sm text-rally-subtle">
              {dashboard.empty_states.map((state) => (
                <li key={state}>{state}</li>
              ))}
            </ul>
          </Card>
        ) : null}

        <Card p={24} className="flex flex-col gap-6">
          <div className="flex flex-col gap-6 sm:flex-row sm:items-center sm:justify-between">
            <div>
              <Overline>Operations summary</Overline>
              <div className="mt-2">
                <BigNum size={32}>
                  {dashboard ? formatInteger(dashboard.sessions.scheduled_count + dashboard.sessions.completed_count) : "No data"}
                </BigNum>
              </div>
              <p className="text-sm text-neutral-500 mt-1">
                Scheduled and completed sessions in {formatMonth(period)}.
              </p>
            </div>
            <dl className="grid min-w-64 gap-3 sm:grid-cols-2">
              <DashboardTerm label="Completed" value={dashboard ? formatInteger(dashboard.sessions.completed_count) : "No data"} />
              <DashboardTerm label="Cancelled" value={dashboard ? formatInteger(dashboard.sessions.cancelled_count) : "No data"} />
              <DashboardTerm label="Seats" value={dashboard ? `${formatInteger(dashboard.sessions.enrolled_seats)} / ${formatInteger(dashboard.sessions.capacity)}` : "No data"} />
              <DashboardTerm label="Attendance marks" value={dashboard ? formatInteger(dashboard.attendance.recorded_count) : "No data"} />
              <DashboardTerm label="Waitlist" value={dashboard ? formatInteger(dashboard.sessions.waitlist_count) : "No data"} />
            </dl>
          </div>
          <dl className="grid gap-3 border-t border-neutral-100 pt-4 sm:grid-cols-3">
            <DashboardTerm label="Present / late" value={dashboard ? formatInteger(dashboard.attendance.present_count) : "No data"} />
            <DashboardTerm label="Recorded attendance" value={dashboard ? formatInteger(dashboard.attendance.recorded_count) : "No data"} />
            <DashboardTerm label="Period" value={formatMonth(period)} />
          </dl>
        </Card>

        <div className="grid gap-4 lg:grid-cols-2">
          <Card p={24}>
            <Overline>Profit and loss</Overline>
            <dl className="mt-4 grid gap-3 sm:grid-cols-2">
              <DashboardTerm label="Revenue" value={dashboard ? formatCurrency(dashboard.profit_and_loss.revenue_cents) : "No data"} />
              <DashboardTerm label="Coach payroll" value={dashboard ? formatNullableCurrency(dashboard.profit_and_loss.coach_payroll_cents) : "No data"} />
              <DashboardTerm label="Rent" value={dashboard ? formatCurrency(dashboard.profit_and_loss.rent_cents) : "No data"} />
              <DashboardTerm label="Misc expenses" value={dashboard ? formatCurrency(dashboard.profit_and_loss.misc_expenses_cents) : "No data"} />
              <DashboardTerm label="Net profit" value={dashboard ? formatNullableCurrency(dashboard.profit_and_loss.net_profit_cents) : "No data"} />
              <DashboardTerm label="Margin" value={dashboard ? formatNullablePercent(dashboard.profit_and_loss.profit_margin) : "No data"} />
            </dl>
          </Card>

          <Card p={24}>
            <Overline>Collections risk</Overline>
            <dl className="mt-4 grid gap-3 sm:grid-cols-2">
              <DashboardTerm label="Families due" value={dashboard ? formatInteger(dashboard.collections_risk.overdue_family_count) : "No data"} />
              <DashboardTerm label="Amount due" value={dashboard ? formatCurrency(dashboard.collections_risk.overdue_cents) : "No data"} />
              <DashboardTerm label="Failed payments" value={dashboard ? formatInteger(dashboard.collections_risk.failed_payment_count) : "No data"} />
              <DashboardTerm label="Partial payments" value={dashboard ? formatInteger(dashboard.collections_risk.partial_payment_count) : "No data"} />
            </dl>
            {dashboard?.collections_risk.aging_buckets.length ? (
              <div className="mt-5 overflow-x-auto">
                <table className="w-full min-w-[360px] text-left text-sm">
                  <thead className="text-xs uppercase text-rally-muted">
                    <tr>
                      <th className="px-2 py-2">Age</th>
                      <th className="px-2 py-2">Amount</th>
                      <th className="px-2 py-2">Families</th>
                    </tr>
                  </thead>
                  <tbody className="divide-y divide-rally-line">
                    {dashboard.collections_risk.aging_buckets.map((bucket) => (
                      <tr key={bucket.label}>
                        <td className="px-2 py-2 font-medium text-rally-ink">{bucket.label}</td>
                        <td className="px-2 py-2 text-rally-muted">{formatCurrency(bucket.amount_cents)}</td>
                        <td className="px-2 py-2 text-rally-muted">{formatInteger(bucket.family_count)}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            ) : null}
          </Card>
        </div>

        <div className="grid gap-4 lg:grid-cols-2">
          <Card p={24}>
            <Overline>Expenses</Overline>
            {dashboard?.expenses.by_category.length ? (
              <div className="mt-4 overflow-x-auto">
                <table className="w-full min-w-[360px] text-left text-sm">
                  <thead className="text-xs uppercase text-rally-muted">
                    <tr>
                      <th className="px-2 py-2">Category</th>
                      <th className="px-2 py-2">Amount</th>
                      <th className="px-2 py-2">Rows</th>
                    </tr>
                  </thead>
                  <tbody className="divide-y divide-rally-line">
                    {dashboard.expenses.by_category.map((category) => (
                      <tr key={category.category}>
                        <td className="px-2 py-2 font-medium text-rally-ink">{category.category}</td>
                        <td className="px-2 py-2 text-rally-muted">{formatCurrency(category.amount_cents)}</td>
                        <td className="px-2 py-2 text-rally-muted">{formatInteger(category.count)}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            ) : (
              <p className="mt-3 text-sm text-rally-subtle">No expenses recorded for this month.</p>
            )}
          </Card>

          <Card p={24}>
            <Overline>Coach payroll</Overline>
            <dl className="mt-4 grid gap-3 sm:grid-cols-2">
              <DashboardTerm label="Estimated" value={dashboard ? formatNullableCurrency(dashboard.payroll.estimated_cents) : "No data"} />
              <DashboardTerm label="Approved" value={dashboard ? formatNullableCurrency(dashboard.payroll.approved_cents) : "No data"} />
              <DashboardTerm label="Paid" value={dashboard ? formatNullableCurrency(dashboard.payroll.paid_cents) : "No data"} />
              <DashboardTerm label="Unpaid" value={dashboard ? formatNullableCurrency(dashboard.payroll.unpaid_cents) : "No data"} />
            </dl>
            {dashboard?.payroll.blocked_by ? (
              <p className="mt-4 rounded-md border border-dashed border-rally-line px-3 py-2 text-sm text-rally-subtle">
                {dashboard.payroll.blocked_by}
              </p>
            ) : null}
          </Card>
        </div>

        <Card p={24} className="flex flex-col gap-6">
          <div className="flex flex-col gap-6 sm:flex-row sm:items-center sm:justify-between">
            <div>
              <Overline>Revenue trend</Overline>
              <div className="mt-2">
                <BigNum size={32}>
                  {latestRevenue == null ? "No data" : formatCurrency(latestRevenue)}
                </BigNum>
              </div>
              <p className="text-sm text-neutral-500 mt-1">
                {latestMonth ? `${formatMonth(latestMonth)} collected revenue` : "No monthly revenue rows returned yet."}
              </p>
            </div>
            {revenueQuery.isLoading ? (
              <div className="h-20 w-60 animate-pulse rounded-md bg-neutral-100 dark:bg-neutral-800" />
            ) : chartValues.length > 0 ? (
              <div className="shrink-0" aria-label="Revenue by month">
                <MiniBars values={chartValues} w={240} h={80} highlight={chartValues.length - 1} />
              </div>
            ) : (
              <div className="rounded-md border border-dashed border-rally-line px-4 py-5 text-sm text-rally-subtle">
                Revenue will appear here after collected payment rows are available.
              </div>
            )}
          </div>
          <dl className="grid gap-3 border-t border-neutral-100 pt-4 sm:grid-cols-3">
            <DashboardTerm label="Months shown" value={String(last6Months.length)} />
            <DashboardTerm label="Six-month total" value={formatCurrency(sixMonthRevenue)} />
            <DashboardTerm label="Latest month" value={latestMonth ? formatMonth(latestMonth) : "Not available"} />
          </dl>
        </Card>
      </div>

      <div className="space-y-3">
        <div>
          <Overline>Exports</Overline>
          <p className="mt-1 text-sm text-neutral-500">
            Download CSV only after reviewing the in-app dashboard above.
          </p>
        </div>
        <div className="grid gap-4 lg:grid-cols-3">
          {REPORTS.map((report) => (
            <Card
              key={report.name}
              p={20}
              className="flex flex-col"
            >
              <h2 className="font-semibold text-lg">{report.title}</h2>
              <p className="mt-1 min-h-[3rem] text-sm text-neutral-500 flex-1">{report.description}</p>
              <div className="mt-4">
                <Button
                  variant="secondary"
                  onClick={() => exportMutation.mutate(report)}
                  disabled={exportMutation.isPending}
                  full
                >
                  {exportMutation.isPending && exportMutation.variables?.name === report.name ? "Exporting..." : "Export CSV"}
                </Button>
              </div>
            </Card>
          ))}
        </div>
      </div>

      {exportMutation.isError && (
        <p role="alert" className="rounded-md bg-red-50 p-3 text-sm text-red-700">
          Could not export that report.
        </p>
      )}

      {preview && (
        <Card p={20}>
          <div className="flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between">
            <h2 className="text-lg font-semibold">{preview.title} preview</h2>
            <Button
              variant="primary"
              onClick={() => downloadCsv(preview.title, preview.csv)}
            >
              Download
            </Button>
          </div>
          <pre className="mt-4 max-h-80 overflow-auto rounded-md bg-neutral-950 p-3 text-xs text-neutral-100">
            {preview.csv}
          </pre>
        </Card>
      )}
    </section>
  );
}

function KpiCard({
  label,
  value,
  description,
}: {
  label: string;
  value: string;
  description: string;
}) {
  return (
    <Card p={20} className="flex flex-col">
      <Overline>{label}</Overline>
      <BigNum size={28}>{value}</BigNum>
      <p className="mt-2 text-[12px] text-rally-muted">{description}</p>
    </Card>
  );
}

function DashboardTerm({ label, value }: { label: string; value: string }) {
  return (
    <div>
      <Overline>{label}</Overline>
      <dd className="mt-1 text-sm font-semibold text-rally-ink">{value}</dd>
    </div>
  );
}

function formatInteger(value: number): string {
  return new Intl.NumberFormat("en-US").format(value);
}

function formatPercent(value: number): string {
  return new Intl.NumberFormat("en-US", {
    style: "percent",
    maximumFractionDigits: 0,
  }).format(value);
}

function formatNullablePercent(value: number | null): string {
  return value == null ? "No records" : formatPercent(value);
}

function formatCurrency(cents: number) {
  return new Intl.NumberFormat("en-US", { style: "currency", currency: "USD" }).format(cents / 100);
}

function formatNullableCurrency(cents: number | null) {
  return cents == null ? "Not available" : formatCurrency(cents);
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
  anchor.download = `${title.toLowerCase().replace(/\s+/g, "-")}.csv`;
  anchor.click();
  URL.revokeObjectURL(url);
}
