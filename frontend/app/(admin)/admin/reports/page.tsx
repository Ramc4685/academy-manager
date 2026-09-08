"use client";

import { useMemo, useState } from "react";
import { useMutation, useQuery } from "@tanstack/react-query";
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

import type { Route } from "next";
import Link from "next/link";

import {
  exportAdminReportCsv,
  getAdminMonthClose,
  getAdminProjectedIncome,
  getAdminReportsDashboard,
  getRevenue,
  sendDuesReminders,
} from "@/lib/api/admin";
import { formatCents, formatDateOnly } from "@/lib/money";
import { invoiceStatusChip } from "@/lib/billing-status";
import {
  autopayRunBox,
  formatCollectionRate,
  monthCloseTiles,
  normalizeMonthClose,
  oddRows,
  warningLine,
} from "@/lib/month-close-view";
import { Card } from "@/components/ds/card";
import { Chip } from "@/components/ds/chip";
import { Button } from "@/components/ds/button";
import { BigNum, Overline } from "@/components/ds/typography";
import { FunnelPanel } from "@/components/admin/reports/funnel-panel";
import { AttendanceTrendsPanel } from "@/components/admin/reports/attendance-trends-panel";
import { CoachUtilizationPanel } from "@/components/admin/reports/coach-utilization-panel";

const FINANCIAL_REPORTS = [
  {
    href: "/admin/reports/session-economics",
    title: "Session economics",
    description: "Revenue, cost and profit by session.",
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

export default function AdminMonthClosePage() {
  const [period, setPeriod] = useState(() => currentPeriod());
  const [expandedBucket, setExpandedBucket] = useState<string | null>(null);
  const [expandedOdd, setExpandedOdd] = useState<string | null>(null);
  const [actionNote, setActionNote] = useState<{ key: string; text: string; ok: boolean } | null>(
    null,
  );

  const monthCloseQuery = useQuery({
    queryKey: ["admin", "reports", "month-close", period],
    queryFn: () => getAdminMonthClose(period),
  });

  const revenueQuery = useQuery({
    queryKey: ["admin", "revenue"],
    queryFn: getRevenue,
  });

  const dashboardQuery = useQuery({
    queryKey: ["admin", "reports", "dashboard", period],
    queryFn: () => getAdminReportsDashboard(period),
  });

  const trailingPeriods = useMemo(() => lastThreeMonths(period), [period]);

  const projectionPeriod = nextPeriod(period);
  const projectedIncomeQuery = useQuery({
    queryKey: ["admin", "reports", "projected-income", projectionPeriod],
    queryFn: () => getAdminProjectedIncome(projectionPeriod),
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

  const quickbooksMutation = useMutation({
    mutationFn: () => exportAdminReportCsv("quickbooks", period),
    onSuccess: (csv) => downloadCsv(`quickbooks-${period}`, csv),
  });

  const depositSlipMutation = useMutation({
    mutationFn: () => exportAdminReportCsv("deposit-slip", period),
    onSuccess: (csv) => downloadCsv(`deposit-slip-${period}`, csv),
  });

  // Normalized, so a partial payload renders zeros instead of crashing the page.
  const close = useMemo(
    () => normalizeMonthClose(monthCloseQuery.data, period),
    [monthCloseQuery.data, period],
  );
  const tiles = monthCloseTiles(close);
  const runBox = autopayRunBox(close);
  const odd = oddRows(close);
  const warning = warningLine(close);
  const discounts = close.tuition_discounts;
  const closeLoading = monthCloseQuery.isLoading;

  const revenueData = revenueQuery.data;
  const trendData = useMemo(
    () => buildRevenueTrend(revenueData?.by_month ?? {}, Number(period.slice(0, 4))),
    [revenueData, period],
  );
  const dashboard = dashboardQuery.data;
  // A resolved query only guarantees the envelope, not the objects inside it,
  // so each group this page reads is guarded on its own rather than on
  // `dashboard` being truthy. A group that is missing renders "No data" —
  // the same thing the page already showed before the query resolved.
  const attendance = dashboard?.attendance;
  const sessions = dashboard?.sessions;
  const profitAndLoss = dashboard?.profit_and_loss;
  const expenses = dashboard?.expenses;
  const payroll = dashboard?.payroll;
  const collectionsRisk = dashboard?.collections_risk;
  // The backend decides whether payroll is complete enough for a final P&L;
  // this page only presents the reason it gives.
  // #667's guards, kept: a resolved query only guarantees the envelope, not
  // the nested objects. The payment-feed and failed-attempt guards it added
  // are gone with the sections they protected — the feed lives on the
  // dashboard and failed autopay is a Payments bucket.
  const payrollBlockedBy = payroll?.blocked_by ?? null;
  const dashboardEmptyStates = dashboard?.empty_states ?? [];
  const agingBuckets = collectionsRisk?.aging_buckets ?? [];
  const expenseCategories = expenses?.by_category ?? [];
  const projected = projectedIncomeQuery.data;
  const projectedSessions = projected?.by_session ?? [];

  return (
    <section data-testid="admin-month-close" className="space-y-5">
      <div className="space-y-3">
        <div className="flex flex-col gap-3 sm:flex-row sm:items-end sm:justify-between">
          <div>
            <Overline>Month close</Overline>
            <p className="mt-1 text-sm text-rally-subtle">
              What the two monthly runs produced for {formatMonth(period)}, and anything that
              looks wrong.
            </p>
          </div>
          <div className="flex flex-wrap items-end gap-3">
            <label className="flex flex-col gap-1 text-sm font-medium text-rally-ink">
              Month
              <input
                type="month"
                value={period}
                onChange={(event) => setPeriod(event.target.value || currentPeriod())}
                data-testid="month-close-period"
                className="h-10 rounded-md border border-rally-line bg-white px-3 text-sm text-rally-ink shadow-sm focus:border-rally-accent focus:outline-none focus:ring-2 focus:ring-rally-accent/20 dark:bg-neutral-950"
              />
            </label>
            <Button
              variant="secondary"
              onClick={() => quickbooksMutation.mutate()}
              disabled={quickbooksMutation.isPending}
              data-testid="export-quickbooks"
            >
              {quickbooksMutation.isPending ? "Exporting..." : "QuickBooks journal"}
            </Button>
            <Button
              variant="secondary"
              onClick={() => depositSlipMutation.mutate()}
              disabled={depositSlipMutation.isPending}
              data-testid="export-deposit-slip"
            >
              {depositSlipMutation.isPending ? "Exporting..." : "Deposit slip"}
            </Button>
          </div>
        </div>

        {(quickbooksMutation.isError || depositSlipMutation.isError) && (
          <p role="alert" className="rounded-md bg-red-50 p-3 text-sm text-red-700">
            Could not export that report.
          </p>
        )}

        {monthCloseQuery.isError && (
          <p role="alert" className="rounded-md bg-red-50 p-3 text-sm text-red-700">
            Could not load month close.
          </p>
        )}

        {warning && (
          <p className="text-sm text-rally-subtle" data-testid="month-close-warnings">
            {warning}
          </p>
        )}

        <div data-testid="month-close-tiles" className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
          {tiles.map((tile) => (
            <Card key={tile.key} p={20} className="flex flex-col">
              <div data-testid={`month-close-tile-${tile.key}`}>
                <Overline>{tile.label}</Overline>
                <BigNum size={28}>
                  <span data-testid={`month-close-tile-${tile.key}-value`}>
                    {closeLoading
                      ? "Loading"
                      : tile.cents != null
                        ? formatCents(tile.cents)
                        : tile.value}
                  </span>
                </BigNum>
                <p className="mt-2 text-[12px] text-rally-muted">{tile.hint}</p>
              </div>
            </Card>
          ))}
        </div>

        <div className="grid gap-4 lg:grid-cols-2">
          <Card p={24} data-testid="autopay-run-box">
            <Overline>Autopay run</Overline>
            <p className="mt-1 text-sm text-rally-subtle" data-testid="autopay-run-headline">
              {runBox.state === "none"
                ? "No autopay invoices this month."
                : `${runBox.hasRun ? "Ran" : "Runs on"} ${formatDateOnly(runBox.chargeOn)}${
                    runBox.chargeOnVaries ? " and later" : ""
                  }.`}
            </p>
            <dl className="mt-4 space-y-2">
              {runBox.rows.map((row) => (
                <div
                  key={row.key}
                  className="flex items-baseline justify-between gap-3 text-sm"
                  data-testid={`autopay-run-${row.key}`}
                >
                  <dt className="text-rally-muted">{row.label}</dt>
                  <dd className="font-mono tabular-nums font-semibold text-rally-ink">
                    {row.countLabel} · {formatCents(row.cents)}
                  </dd>
                </div>
              ))}
            </dl>
            {runBox.hasRun && close.autopay_run.failed.count > 0 ? (
              <Link
                href="/admin/payments"
                data-testid="autopay-run-failed-link"
                className="mt-4 inline-block text-sm font-medium text-rally-accent hover:underline"
              >
                Work the Failed autopay bucket
              </Link>
            ) : null}
          </Card>

          <Card p={24} data-testid="anything-odd-box">
            <Overline>Anything odd</Overline>
            <p className="mt-1 text-sm text-rally-subtle">
              Four checks over this month&apos;s invoices. A zero is the answer you want.
            </p>
            <ul className="mt-4 space-y-2">
              {odd.map((row) => (
                <li
                  key={row.code}
                  className="rounded-md border border-rally-line"
                  data-testid={`odd-${row.code}`}
                >
                  <button
                    type="button"
                    className="flex w-full items-center justify-between gap-3 px-3 py-2 text-left text-sm hover:bg-rally-line/20 disabled:cursor-default"
                    onClick={() => setExpandedOdd(expandedOdd === row.code ? null : row.code)}
                    disabled={!row.expandable}
                    aria-expanded={expandedOdd === row.code}
                  >
                    <span className="text-rally-ink">{row.label}</span>
                    <span className="font-mono tabular-nums font-semibold text-rally-muted">
                      <span data-testid={`odd-${row.code}-count`}>{row.count}</span>
                      {row.expandable ? (
                        <span className="ml-2 text-xs">
                          {expandedOdd === row.code ? "Hide" : "View"}
                        </span>
                      ) : null}
                    </span>
                  </button>
                  {expandedOdd === row.code && row.items.length > 0 ? (
                    <ul
                      className="divide-y divide-rally-line border-t border-rally-line"
                      data-testid={`odd-${row.code}-items`}
                    >
                      {row.items.map((item) => (
                        <li key={`${item.kind}:${item.id}`} className="px-3 py-2 text-sm">
                          <Link
                            href={item.href as Route}
                            className="font-medium text-rally-accent hover:underline"
                          >
                            {item.label}
                          </Link>
                        </li>
                      ))}
                      {row.truncatedNote ? (
                        <li className="px-3 py-2 text-xs text-rally-subtle">{row.truncatedNote}</li>
                      ) : null}
                    </ul>
                  ) : null}
                </li>
              ))}
            </ul>
          </Card>
        </div>

        {close.invoices.void_reasons.length > 0 ? (
          <Card p={20} data-testid="void-reasons">
            <div className="flex items-center gap-3">
              <Overline>Why invoices were voided</Overline>
              <Chip {...invoiceStatusChip("void")} />
            </div>
            <ul className="mt-3 space-y-1 text-sm text-rally-subtle">
              {close.invoices.void_reasons.map((entry) => (
                <li key={entry.reason}>
                  {entry.reason} — {entry.count}
                </li>
              ))}
            </ul>
            <p className="mt-2 text-xs text-rally-muted">
              {formatCents(close.invoices.voided_cents)} voided in total.
            </p>
          </Card>
        ) : null}

        <Card p={24} data-testid="tuition-discounts-section" className="space-y-4">
          <div>
            <Overline>Tuition discounts</Overline>
            <p className="mt-1 text-sm text-neutral-500">
              Gross tuition vs. discounts granted in {formatMonth(period)}.
            </p>
          </div>
          {discounts === null ? (
            <p className="text-sm text-rally-subtle" data-testid="tuition-discounts-unavailable">
              {closeLoading ? "Loading…" : "The tuition discount summary is not available."}
            </p>
          ) : (
            <>
              <div className="grid gap-3 sm:grid-cols-3">
                <DashboardTerm label="Gross tuition" value={formatCents(discounts.gross_cents)} />
                <DashboardTerm
                  label="Total discounts"
                  value={formatCents(discounts.discount_cents)}
                />
                <DashboardTerm label="Net tuition" value={formatCents(discounts.net_cents)} />
              </div>
              {discounts.by_category.length === 0 ? (
                <p data-testid="tuition-discounts-empty" className="text-sm text-neutral-500">
                  No discounts recorded for this month.
                </p>
              ) : (
                <div className="overflow-x-auto rounded-lg border border-neutral-200 bg-white dark:border-neutral-800 dark:bg-neutral-900">
                  <table className="w-full min-w-[480px] text-sm">
                    <thead>
                      <tr className="border-b border-neutral-200 text-left text-neutral-500 dark:border-neutral-800">
                        <th className="px-4 py-3 font-mono text-[10px] font-bold uppercase tracking-overline text-rally-muted">
                          Category
                        </th>
                        <th className="px-4 py-3 text-right font-mono text-[10px] font-bold uppercase tracking-overline text-rally-muted">
                          Discount
                        </th>
                        <th className="px-4 py-3 text-right font-mono text-[10px] font-bold uppercase tracking-overline text-rally-muted">
                          % of gross
                        </th>
                      </tr>
                    </thead>
                    <tbody>
                      {discounts.by_category.map((row) => (
                        <tr
                          key={row.category}
                          data-testid={`tuition-discounts-row-${row.category}`}
                          className="border-b border-neutral-100 last:border-0 dark:border-neutral-800"
                        >
                          <td className="px-4 py-3 font-medium">{row.category}</td>
                          <td className="px-4 py-3 text-right font-mono tabular-nums">
                            {formatCents(row.amount_cents)}
                          </td>
                          <td className="px-4 py-3 text-right font-mono tabular-nums">
                            {discounts.gross_cents > 0
                              ? `${((row.amount_cents / discounts.gross_cents) * 100).toFixed(1)}%`
                              : "—"}
                          </td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              )}
            </>
          )}
        </Card>

        <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
          <KpiCard
            label="Attendance rate"
            value={attendance ? formatNullablePercent(attendance.attendance_rate) : dashboardQuery.isLoading ? "Loading" : "No data"}
            description="Present or late marks out of recorded attendance."
          />
          <KpiCard
            label="Capacity used"
            value={sessions ? formatNullablePercent(sessions.capacity_utilization) : dashboardQuery.isLoading ? "Loading" : "No data"}
            description="Enrolled seats against scheduled and completed capacity."
          />
          <KpiCard
            label="Net profit"
            value={
              payrollBlockedBy
                ? "Blocked"
                : profitAndLoss
                  ? formatNullableCurrency(profitAndLoss.net_profit_cents)
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
            value={expenses ? formatCents(expenses.total_cents) : dashboardQuery.isLoading ? "Loading" : "No data"}
            description="Recorded rent, equipment, salary, marketing, and other spend."
          />
          <KpiCard
            label="Payroll unpaid"
            value={payroll ? formatNullableCurrency(payroll.unpaid_cents) : dashboardQuery.isLoading ? "Loading" : "No data"}
            description="Approved coach payout amount not yet marked paid."
          />
          <KpiCard
            label="Waitlist"
            value={sessions ? formatInteger(sessions.waitlist_count) : dashboardQuery.isLoading ? "Loading" : "No data"}
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

        <Card p={24} className="flex flex-col gap-6">
          <div className="flex flex-col gap-6 sm:flex-row sm:items-center sm:justify-between">
            <div>
              <Overline>Operations summary</Overline>
              <div className="mt-2">
                <BigNum size={32}>
                  {sessions ? formatInteger(sessions.scheduled_count + sessions.completed_count) : "No data"}
                </BigNum>
              </div>
              <p className="text-sm text-neutral-500 mt-1">
                Scheduled and completed sessions in {formatMonth(period)}.
              </p>
            </div>
            <dl className="grid min-w-64 gap-3 sm:grid-cols-2">
              <DashboardTerm label="Completed" value={sessions ? formatInteger(sessions.completed_count) : "No data"} />
              <DashboardTerm label="Cancelled" value={sessions ? formatInteger(sessions.cancelled_count) : "No data"} />
              <DashboardTerm label="Seats" value={sessions ? `${formatInteger(sessions.enrolled_seats)} / ${formatInteger(sessions.capacity)}` : "No data"} />
              <DashboardTerm label="Attendance marks" value={attendance ? formatInteger(attendance.recorded_count) : "No data"} />
              <DashboardTerm label="Waitlist" value={sessions ? formatInteger(sessions.waitlist_count) : "No data"} />
            </dl>
          </div>
          <dl className="grid gap-3 border-t border-neutral-100 pt-4 sm:grid-cols-3">
            <DashboardTerm label="Present / late" value={attendance ? formatInteger(attendance.present_count) : "No data"} />
            <DashboardTerm label="Recorded attendance" value={attendance ? formatInteger(attendance.recorded_count) : "No data"} />
            <DashboardTerm label="Period" value={formatMonth(period)} />
          </dl>
        </Card>

        <div className="grid gap-4 lg:grid-cols-2">
          <Card p={24}>
            <Overline>Profit and loss</Overline>
            <dl className="mt-4 grid gap-3 sm:grid-cols-2">
              <DashboardTerm label="Revenue" value={profitAndLoss ? formatCents(profitAndLoss.revenue_cents) : "No data"} />
              <DashboardTerm label="Coach payroll" value={profitAndLoss ? formatNullableCurrency(profitAndLoss.coach_payroll_cents) : "No data"} />
              <DashboardTerm label="Rent" value={profitAndLoss ? formatCents(profitAndLoss.rent_cents) : "No data"} />
              <DashboardTerm label="Misc expenses" value={profitAndLoss ? formatCents(profitAndLoss.misc_expenses_cents) : "No data"} />
              <DashboardTerm label="Net profit" value={profitAndLoss ? formatNullableCurrency(profitAndLoss.net_profit_cents) : "No data"} />
              <DashboardTerm label="Margin" value={profitAndLoss ? formatNullablePercent(profitAndLoss.profit_margin) : "No data"} />
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
              <DashboardTerm label="Families due" value={collectionsRisk ? formatInteger(collectionsRisk.overdue_family_count) : "No data"} />
              <DashboardTerm label="Amount due" value={collectionsRisk ? formatCents(collectionsRisk.overdue_cents) : "No data"} />
              <DashboardTerm label="Failed payments" value={collectionsRisk ? formatInteger(collectionsRisk.failed_payment_count) : "No data"} />
              <DashboardTerm label="Partial payments" value={collectionsRisk ? formatInteger(collectionsRisk.partial_payment_count) : "No data"} />
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
                        {formatCents(bucket.amount_cents)} · {formatInteger(bucket.family_count)}{" "}
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
                                {formatCents(family.amount_cents)}
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
                        <td className="px-2 py-2 text-rally-muted">{formatCents(category.amount_cents)}</td>
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
              <DashboardTerm label="Estimated" value={payroll ? formatNullableCurrency(payroll.estimated_cents) : "No data"} />
              <DashboardTerm label="Approved" value={payroll ? formatNullableCurrency(payroll.approved_cents) : "No data"} />
              <DashboardTerm label="Paid" value={payroll ? formatNullableCurrency(payroll.paid_cents) : "No data"} />
              <DashboardTerm label="Unpaid" value={payroll ? formatNullableCurrency(payroll.unpaid_cents) : "No data"} />
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
                ? formatCents(projected.total_cents)
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
                    value={formatCents(projected.autopay_cents)}
                  />
                  <DashboardTerm
                    label={`Manual (${formatInteger(projected.manual_enrollment_count)})`}
                    value={formatCents(projected.manual_cents)}
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
                        <td className="px-2 py-2 text-rally-muted">{formatCents(row.monthly_fee_cents)}</td>
                        <td className="px-2 py-2 text-rally-muted">{formatCents(row.expected_cents)}</td>
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
                  <Tooltip formatter={(value) => formatCents(Number(value ?? 0) * 100)} />
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
            Monthly reports over the billing ledger.
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
        </div>
      </div>
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

/** A share the backend already computed; `null` means "no records", not 0%. */
function formatNullablePercent(value: number | null): string {
  return value == null ? "No records" : formatCollectionRate(value);
}

function formatNullableCurrency(cents: number | null) {
  return cents == null ? "Not available" : formatCents(cents);
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
