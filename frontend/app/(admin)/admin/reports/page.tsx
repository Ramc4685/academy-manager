"use client";

import { useMemo, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  Bar,
  BarChart,
  CartesianGrid,
  Legend,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";

import Link from "next/link";

import {
  chargeAdminInvoiceAutopay,
  exportAdminReportCsv,
  fetchFailedPaymentAttempts,
  getAdminPaymentFeed,
  getAdminProjectedIncome,
  getAdminReportsDashboard,
  getRevenue,
  sendDuesReminders,
} from "@/lib/api/admin";
import { queryKeys } from "@/lib/query/keys";
import { paymentMethodLabel } from "@/app/(admin)/admin/payments/format";
import { Card } from "@/components/ds/card";
import { Button } from "@/components/ds/button";
import { BigNum, Overline } from "@/components/ds/typography";
import { FunnelPanel } from "@/components/admin/reports/funnel-panel";
import { AttendanceTrendsPanel } from "@/components/admin/reports/attendance-trends-panel";
import { CoachUtilizationPanel } from "@/components/admin/reports/coach-utilization-panel";

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

const FINANCIAL_REPORTS = [
  {
    href: "/admin/reports/session-economics",
    title: "Session economics",
    description: "Revenue, cost and profit by session.",
  },
  {
    href: "/admin/reports/dues",
    title: "Dues follow-up",
    description: "Outstanding balances and reminders.",
  },
  {
    href: "/admin/reports/refunds",
    title: "Refunds & credits",
    description: "Money returned to families and account credits issued, by month.",
  },
  {
    href: "/admin/reports/revenue-by-category",
    title: "Revenue by category",
    description: "Collected revenue split by program and fee category.",
  },
  {
    href: "/admin/reports/deposit-slip",
    title: "Deposit slip",
    description: "Payments received by day and method for bank reconciliation.",
  },
] as const;

export default function AdminReportsPage() {
  const queryClient = useQueryClient();
  const [preview, setPreview] = useState<{ title: string; csv: string } | null>(null);
  const [period, setPeriod] = useState(() => currentPeriod());
  const [expandedBucket, setExpandedBucket] = useState<string | null>(null);
  const [actionNote, setActionNote] = useState<{ key: string; text: string; ok: boolean } | null>(
    null,
  );

  const revenueQuery = useQuery({
    queryKey: ["admin", "revenue"],
    queryFn: getRevenue,
  });

  const dashboardQuery = useQuery({
    queryKey: ["admin", "reports", "dashboard", period],
    queryFn: () => getAdminReportsDashboard(period),
  });

  const paymentFeedQuery = useQuery({
    queryKey: queryKeys.admin.paymentFeed(10),
    queryFn: () => getAdminPaymentFeed(10),
  });

  const failedPaymentsQuery = useQuery({
    queryKey: ["admin", "billing", "failed-payment-attempts"],
    queryFn: fetchFailedPaymentAttempts,
  });

  const trailingPeriods = useMemo(() => lastThreeMonths(period), [period]);

  const projectionPeriod = nextPeriod(period);
  const projectedIncomeQuery = useQuery({
    queryKey: ["admin", "reports", "projected-income", projectionPeriod],
    queryFn: () => getAdminProjectedIncome(projectionPeriod),
  });

  const retryMutation = useMutation({
    mutationFn: (invoiceId: string) => chargeAdminInvoiceAutopay(invoiceId),
    onSuccess: (result, invoiceId) => {
      setActionNote({
        key: `retry:${invoiceId}`,
        text: result.success
          ? "Charge succeeded."
          : result.requires_action
            ? "Charge needs parent action (3DS)."
            : `Charge declined${result.decline_code ? ` (${result.decline_code})` : ""}.`,
        ok: Boolean(result.success),
      });
      void queryClient.invalidateQueries({
        queryKey: ["admin", "billing", "failed-payment-attempts"],
      });
      void queryClient.invalidateQueries({ queryKey: ["admin", "reports", "dashboard"] });
    },
    onError: (_error, invoiceId) => {
      setActionNote({ key: `retry:${invoiceId}`, text: "Retry failed. Try again.", ok: false });
    },
  });

  const notifyMutation = useMutation({
    mutationFn: (parentId: string) => sendDuesReminders({ parent_ids: [parentId] }),
    onSuccess: (result, parentId) => {
      setActionNote({
        key: `notify:${parentId}`,
        text: result.blocked
          ? `Reminder blocked${result.reason ? `: ${result.reason}` : "."}`
          : result.sent > 0
            ? "Reminder sent."
            : "No reminder sent — family has no open dues on file.",
        ok: !result.blocked && result.sent > 0,
      });
    },
    onError: (_error, parentId) => {
      setActionNote({ key: `notify:${parentId}`, text: "Could not send reminder.", ok: false });
    },
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

  const quickbooksMutation = useMutation({
    mutationFn: () => exportAdminReportCsv("quickbooks", period),
    onSuccess: (csv) => downloadCsv(`quickbooks-${period}`, csv),
  });

  const revenueData = revenueQuery.data;
  const trendData = useMemo(
    () => buildRevenueTrend(revenueData?.by_month ?? {}, Number(period.slice(0, 4))),
    [revenueData, period],
  );
  const dashboard = dashboardQuery.data;
  // The backend decides whether payroll is complete enough for a final P&L;
  // this page only presents the reason it gives.
  const payrollBlockedBy = dashboard?.payroll?.blocked_by ?? null;
  const dashboardEmptyStates = dashboard?.empty_states ?? [];
  const agingBuckets = dashboard?.collections_risk?.aging_buckets ?? [];
  const expenseCategories = dashboard?.expenses?.by_category ?? [];
  const recentPayments = paymentFeedQuery.data?.payments ?? [];
  const failedRows = failedPaymentsQuery.data?.rows ?? [];
  const failedTotalCents = failedRows.reduce((total, row) => total + row.balance_due_cents, 0);
  const projected = projectedIncomeQuery.data;
  const projectedSessions = projected?.by_session ?? [];

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
        <div data-testid="reports-money-tiles" className="grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
          <KpiCard
            label="Billed this month"
            value={dashboard ? formatCurrency(dashboard.billed_cents) : dashboardQuery.isLoading ? "Loading" : "No data"}
            description="Tuition and fees invoiced for the selected month."
          />
          <KpiCard
            label="Collected"
            value={dashboard ? formatCurrency(dashboard.cash_collected_cents) : dashboardQuery.isLoading ? "Loading" : "No data"}
            description="Cash received this month, net of refunds."
          />
          <KpiCard
            label="Outstanding"
            value={dashboard ? formatCurrency(dashboard.outstanding_dues_cents) : dashboardQuery.isLoading ? "Loading" : "No data"}
            description="Open or partially paid dues still requiring follow-up."
          />
          <KpiCard
            label="Collection rate"
            value={dashboard ? formatNullablePercent(dashboard.collection_rate) : dashboardQuery.isLoading ? "Loading" : "No data"}
            description="Collected as a share of what was billed this month."
          />
        </div>

        {failedRows.length > 0 && (
          <Card
            p={24}
            data-testid="failed-autopay-alert"
            className="border-2 border-red-300 bg-red-50/60 dark:border-red-900 dark:bg-red-950/30"
          >
            <div className="flex flex-col gap-2 sm:flex-row sm:items-center sm:justify-between">
              <div>
                <Overline>Failed autopay — action needed</Overline>
                <div className="mt-1">
                  <BigNum size={28}>
                    {formatInteger(failedRows.length)} {failedRows.length === 1 ? "payment" : "payments"} · {formatCurrency(failedTotalCents)}
                  </BigNum>
                </div>
                <p className="mt-1 text-sm text-red-700 dark:text-red-300">
                  These charges declined and the invoices are still unpaid.
                </p>
              </div>
            </div>
            <ul className="mt-4 divide-y divide-red-200 dark:divide-red-900">
              {failedRows.map((row) => (
                <li
                  key={row.invoice_id}
                  className="flex flex-col gap-2 py-3 sm:flex-row sm:items-center sm:justify-between"
                >
                  <div>
                    <p className="text-sm font-semibold text-rally-ink">
                      {row.parent_name || row.parent_id}
                    </p>
                    <p className="text-xs text-rally-muted">
                      {formatCurrency(row.balance_due_cents)} due · {row.period}
                      {row.latest_decline_code ? ` · ${row.latest_decline_code}` : ""}
                      {row.attempt_count ? ` · ${row.attempt_count} attempts` : ""}
                    </p>
                    {actionNote &&
                    (actionNote.key === `retry:${row.invoice_id}` ||
                      actionNote.key === `notify:${row.parent_id}`) ? (
                      <p
                        className={`mt-1 text-xs ${actionNote.ok ? "text-emerald-700" : "text-red-700"}`}
                      >
                        {actionNote.text}
                      </p>
                    ) : null}
                  </div>
                  <div className="flex shrink-0 gap-2">
                    <Button
                      variant="secondary"
                      onClick={() => retryMutation.mutate(row.invoice_id)}
                      disabled={retryMutation.isPending}
                    >
                      {retryMutation.isPending && retryMutation.variables === row.invoice_id
                        ? "Retrying..."
                        : "Retry charge"}
                    </Button>
                    <Button
                      variant="secondary"
                      onClick={() => notifyMutation.mutate(row.parent_id)}
                      disabled={notifyMutation.isPending}
                    >
                      {notifyMutation.isPending && notifyMutation.variables === row.parent_id
                        ? "Sending..."
                        : "Notify parent"}
                    </Button>
                  </div>
                </li>
              ))}
            </ul>
          </Card>
        )}

        <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
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
            value={
              payrollBlockedBy
                ? "Blocked"
                : dashboard
                  ? formatNullableCurrency(dashboard.profit_and_loss.net_profit_cents)
                  : dashboardQuery.isLoading
                    ? "Loading"
                    : "No data"
            }
            description={
              payrollBlockedBy
                ? `Payroll is incomplete, so profit is not final. ${payrollBlockedBy}`
                : "Revenue less expenses and coach payroll."
            }
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

        {dashboardEmptyStates.length ? (
          <Card p={20}>
            <Overline>Empty states</Overline>
            <ul className="mt-3 space-y-2 text-sm text-rally-subtle">
              {dashboardEmptyStates.map((state) => (
                <li key={state}>{state}</li>
              ))}
            </ul>
          </Card>
        ) : null}

        <Card p={24} data-testid="recent-payments-card">
          <div className="flex items-center justify-between gap-3">
            <Overline>Recent payments</Overline>
            <Link
              href="/admin/payments"
              className="text-sm font-medium text-rally-accent hover:underline"
            >
              View all payments
            </Link>
          </div>
          {paymentFeedQuery.isError ? (
            <p className="mt-3 text-sm text-red-700">Could not load recent payments.</p>
          ) : paymentFeedQuery.isLoading ? (
            <p className="mt-3 text-sm text-rally-subtle">Loading…</p>
          ) : recentPayments.length === 0 ? (
            <p className="mt-3 text-sm text-rally-subtle">No payments received yet.</p>
          ) : (
            <div className="mt-4 divide-y divide-rally-line">
              {recentPayments.map((item) => (
                <div
                  key={item.payment_id}
                  className="flex flex-wrap items-center justify-between gap-2 py-2.5 text-sm"
                >
                  <div>
                    <span className="font-medium text-rally-ink">
                      {item.parent_name || "Family on file"}
                    </span>
                    <span className="ml-2 text-xs text-rally-subtle">
                      {paymentMethodLabel(item.payment_method) || "—"}
                      {item.refunded_cents > 0 ? " · partially refunded" : ""}
                    </span>
                  </div>
                  <div className="flex items-center gap-3">
                    <span className="font-mono font-semibold tabular-nums text-rally-ink">
                      {formatCurrency(item.amount_cents)}
                    </span>
                    <span className="text-xs text-rally-subtle">
                      {new Date(item.paid_at).toLocaleDateString(undefined, {
                        month: "short",
                        day: "numeric",
                      })}
                    </span>
                  </div>
                </div>
              ))}
            </div>
          )}
        </Card>

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
            {payrollBlockedBy ? (
              <p
                className="mt-4 rounded-md border border-dashed border-amber-300 bg-amber-50 px-3 py-2 text-sm text-amber-900"
                data-testid="pnl-payroll-blocked"
              >
                Profit is not final until payroll is complete. {payrollBlockedBy}
              </p>
            ) : null}
          </Card>

          <Card p={24}>
            <Overline>Collections risk</Overline>
            <dl className="mt-4 grid gap-3 sm:grid-cols-2">
              <DashboardTerm label="Families due" value={dashboard ? formatInteger(dashboard.collections_risk.overdue_family_count) : "No data"} />
              <DashboardTerm label="Amount due" value={dashboard ? formatCurrency(dashboard.collections_risk.overdue_cents) : "No data"} />
              <DashboardTerm label="Failed payments" value={dashboard ? formatInteger(dashboard.collections_risk.failed_payment_count) : "No data"} />
              <DashboardTerm label="Partial payments" value={dashboard ? formatInteger(dashboard.collections_risk.partial_payment_count) : "No data"} />
            </dl>
            {agingBuckets.length ? (
              <div className="mt-5 space-y-2" data-testid="ar-aging-widget">
                {agingBuckets.map((bucket) => (
                  <div key={bucket.label} className="rounded-md border border-rally-line">
                    <button
                      type="button"
                      className="flex w-full items-center justify-between px-3 py-2 text-left text-sm hover:bg-rally-line/20 disabled:cursor-default"
                      onClick={() =>
                        setExpandedBucket(expandedBucket === bucket.label ? null : bucket.label)
                      }
                      disabled={bucket.family_count === 0}
                      aria-expanded={expandedBucket === bucket.label}
                    >
                      <span className="font-medium text-rally-ink">{bucket.label}</span>
                      <span className="text-rally-muted">
                        {formatCurrency(bucket.amount_cents)} · {formatInteger(bucket.family_count)}{" "}
                        {bucket.family_count === 1 ? "family" : "families"}
                        {bucket.family_count > 0 ? (
                          <span className="ml-2 text-xs">
                            {expandedBucket === bucket.label ? "Hide" : "View"}
                          </span>
                        ) : null}
                      </span>
                    </button>
                    {expandedBucket === bucket.label && bucket.families.length > 0 ? (
                      <ul className="divide-y divide-rally-line border-t border-rally-line">
                        {bucket.families.map((family) => (
                          <li
                            key={family.family_id}
                            className="flex items-center justify-between gap-2 px-3 py-2 text-sm"
                          >
                            <div>
                              <span className="font-medium text-rally-ink">
                                {family.family_name || family.family_id}
                              </span>
                              <span className="ml-2 text-rally-muted">
                                {formatCurrency(family.amount_cents)}
                              </span>
                              {actionNote && actionNote.key === `notify:${family.family_id}` ? (
                                <p
                                  className={`mt-1 text-xs ${actionNote.ok ? "text-emerald-700" : "text-red-700"}`}
                                >
                                  {actionNote.text}
                                </p>
                              ) : null}
                            </div>
                            <Button
                              variant="secondary"
                              onClick={() => notifyMutation.mutate(family.family_id)}
                              disabled={notifyMutation.isPending}
                            >
                              {notifyMutation.isPending &&
                              notifyMutation.variables === family.family_id
                                ? "Sending..."
                                : "Send reminder"}
                            </Button>
                          </li>
                        ))}
                      </ul>
                    ) : null}
                  </div>
                ))}
              </div>
            ) : null}
          </Card>
        </div>

        <div className="grid gap-4 lg:grid-cols-2">
          <Card p={24}>
            <Overline>Expenses</Overline>
            {expenseCategories.length ? (
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
                    {expenseCategories.map((category) => (
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
            {payrollBlockedBy ? (
              <p className="mt-4 rounded-md border border-dashed border-rally-line px-3 py-2 text-sm text-rally-subtle">
                {payrollBlockedBy}
              </p>
            ) : null}
          </Card>
        </div>

        <Card p={24} data-testid="projected-income-widget">
          <Overline>Projected income — {formatMonth(projectionPeriod)}</Overline>
          <div className="mt-2">
            <BigNum size={32}>
              {projected
                ? formatCurrency(projected.total_cents)
                : projectedIncomeQuery.isLoading
                  ? "Loading"
                  : "No data"}
            </BigNum>
          </div>
          <p className="mt-1 text-sm text-rally-subtle">
            Expected tuition from active enrollments at each session&apos;s monthly fee.
          </p>
          {projected && !projected.empty ? (
            <div className="mt-4 space-y-4">
              <div>
                <div className="flex h-3 w-full overflow-hidden rounded-full bg-rally-line/40">
                  {projected.total_cents > 0 ? (
                    <>
                      <div
                        className="bg-emerald-500"
                        style={{
                          width: `${(projected.autopay_cents / projected.total_cents) * 100}%`,
                        }}
                      />
                      <div
                        className="bg-amber-400"
                        style={{
                          width: `${(projected.manual_cents / projected.total_cents) * 100}%`,
                        }}
                      />
                    </>
                  ) : null}
                </div>
                <dl className="mt-3 grid gap-3 sm:grid-cols-2">
                  <DashboardTerm
                    label={`Autopay (${formatInteger(projected.autopay_enrollment_count)})`}
                    value={formatCurrency(projected.autopay_cents)}
                  />
                  <DashboardTerm
                    label={`Manual (${formatInteger(projected.manual_enrollment_count)})`}
                    value={formatCurrency(projected.manual_cents)}
                  />
                </dl>
              </div>
              <div className="overflow-x-auto">
                <table className="w-full min-w-[360px] text-left text-sm">
                  <thead className="text-xs uppercase text-rally-muted">
                    <tr>
                      <th className="px-2 py-2">Session</th>
                      <th className="px-2 py-2">Students</th>
                      <th className="px-2 py-2">Monthly fee</th>
                      <th className="px-2 py-2">Expected</th>
                    </tr>
                  </thead>
                  <tbody className="divide-y divide-rally-line">
                    {projectedSessions.map((row) => (
                      <tr key={row.session_id}>
                        <td className="px-2 py-2 font-medium text-rally-ink">{row.title || row.session_id}</td>
                        <td className="px-2 py-2 text-rally-muted">{formatInteger(row.enrollment_count)}</td>
                        <td className="px-2 py-2 text-rally-muted">{formatCurrency(row.monthly_fee_cents)}</td>
                        <td className="px-2 py-2 text-rally-muted">{formatCurrency(row.expected_cents)}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </div>
          ) : projectedIncomeQuery.isLoading ? (
            <div className="mt-4 h-20 animate-pulse rounded-md bg-neutral-100 dark:bg-neutral-800" />
          ) : (
            <p className="mt-4 rounded-md border border-dashed border-rally-line px-3 py-2 text-sm text-rally-subtle">
              No active enrollments with a monthly fee yet.
            </p>
          )}
        </Card>

        <Card p={24} data-testid="revenue-trend-chart">
          <Overline>Revenue trend — {period.slice(0, 4)} vs {Number(period.slice(0, 4)) - 1}</Overline>
          <p className="mt-1 text-sm text-rally-subtle">
            Monthly collected revenue (cash basis, net of refunds).
          </p>
          {revenueQuery.isLoading ? (
            <div className="mt-4 h-64 animate-pulse rounded-md bg-neutral-100 dark:bg-neutral-800" />
          ) : trendData.some((row) => row.current > 0 || row.prior > 0) ? (
            <div className="mt-4 h-64 w-full">
              <ResponsiveContainer width="100%" height="100%">
                <BarChart data={trendData} margin={{ top: 8, right: 8, bottom: 0, left: 8 }}>
                  <CartesianGrid strokeDasharray="3 3" vertical={false} stroke="#e5e7eb" />
                  <XAxis dataKey="month" tickLine={false} axisLine={false} fontSize={12} />
                  <YAxis
                    tickFormatter={(value: number) => formatCompactCurrency(value)}
                    tickLine={false}
                    axisLine={false}
                    fontSize={12}
                    width={56}
                  />
                  <Tooltip
                    formatter={(value) => formatCurrency(Number(value ?? 0) * 100)}
                  />
                  <Legend />
                  <Bar
                    dataKey="prior"
                    name={String(Number(period.slice(0, 4)) - 1)}
                    fill="#cbd5e1"
                    radius={[3, 3, 0, 0]}
                  />
                  <Bar
                    dataKey="current"
                    name={period.slice(0, 4)}
                    fill="#2563eb"
                    radius={[3, 3, 0, 0]}
                  />
                </BarChart>
              </ResponsiveContainer>
            </div>
          ) : (
            <p className="mt-4 rounded-md border border-dashed border-rally-line px-3 py-2 text-sm text-rally-subtle">
              Revenue will appear here after collected payment rows are available.
            </p>
          )}
        </Card>
      </div>

      <div className="space-y-3">
        <div>
          <Overline>Analytics</Overline>
          <p className="mt-1 text-sm text-neutral-500">
            Enrollment, attendance, and coach utilization over the trailing three months.
          </p>
        </div>
        <div className="grid gap-4">
          <FunnelPanel period={period} />
          <AttendanceTrendsPanel periods={trailingPeriods} />
          <CoachUtilizationPanel periods={trailingPeriods} />
        </div>
      </div>

      <div className="space-y-3">
        <div>
          <Overline>Financial reports</Overline>
          <p className="mt-1 text-sm text-neutral-500">
            Monthly reports over the billing ledger, with CSV export on each page.
          </p>
        </div>
        <div className="grid gap-4 lg:grid-cols-3">
          {FINANCIAL_REPORTS.map((report) => (
            <Link key={report.href} href={report.href} className="block">
              <Card p={20} className="flex h-full flex-col transition-colors hover:border-rally-accent">
                <h2 className="font-semibold text-lg">{report.title}</h2>
                <p className="mt-1 min-h-[3rem] text-sm text-neutral-500 flex-1">{report.description}</p>
                <span className="mt-4 text-sm font-medium text-rally-accent">Open report</span>
              </Card>
            </Link>
          ))}
          <Card p={20} className="flex flex-col">
            <h2 className="font-semibold text-lg">QuickBooks export</h2>
            <p className="mt-1 min-h-[3rem] text-sm text-neutral-500 flex-1">
              Monthly summary journal entries for {formatMonth(period)}, ready to import into
              QuickBooks Online.
            </p>
            <div className="mt-4">
              <Button
                variant="secondary"
                onClick={() => quickbooksMutation.mutate()}
                disabled={quickbooksMutation.isPending}
                full
              >
                {quickbooksMutation.isPending ? "Exporting..." : "Export journal CSV"}
              </Button>
            </div>
          </Card>
        </div>
        {quickbooksMutation.isError && (
          <p role="alert" className="rounded-md bg-red-50 p-3 text-sm text-red-700">
            Could not export the QuickBooks journal.
          </p>
        )}
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

function nextPeriod(period: string) {
  const [year, month] = period.split("-").map(Number);
  if (!year || !month) return period;
  const nextMonth = month === 12 ? 1 : month + 1;
  const nextYear = month === 12 ? year + 1 : year;
  return `${nextYear}-${String(nextMonth).padStart(2, "0")}`;
}

function lastThreeMonths(period: string): string[] {
  const [year, month] = period.split("-").map(Number);
  if (!year || !month) return [period];
  const result: string[] = [];
  for (let offset = 2; offset >= 0; offset -= 1) {
    const index = month - 1 - offset;
    const wrappedYear = year + Math.floor(index / 12);
    const wrappedMonth = ((index % 12) + 12) % 12;
    result.push(`${wrappedYear}-${String(wrappedMonth + 1).padStart(2, "0")}`);
  }
  return result;
}

const MONTH_LABELS = [
  "Jan",
  "Feb",
  "Mar",
  "Apr",
  "May",
  "Jun",
  "Jul",
  "Aug",
  "Sep",
  "Oct",
  "Nov",
  "Dec",
];

function buildRevenueTrend(
  byMonth: Record<string, number>,
  year: number,
): Array<{ month: string; current: number; prior: number }> {
  return MONTH_LABELS.map((label, index) => {
    const key = `${String(index + 1).padStart(2, "0")}`;
    return {
      month: label,
      current: (byMonth[`${year}-${key}`] ?? 0) / 100,
      prior: (byMonth[`${year - 1}-${key}`] ?? 0) / 100,
    };
  });
}

function formatCompactCurrency(dollars: number) {
  return new Intl.NumberFormat("en-US", {
    style: "currency",
    currency: "USD",
    notation: "compact",
    maximumFractionDigits: 1,
  }).format(dollars);
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
