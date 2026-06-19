"use client";

import { useState } from "react";
import { useQuery } from "@tanstack/react-query";

import { Card } from "@/components/ds/card";
import { BigNum, Overline } from "@/components/ds/typography";
import { getAdminSessionEconomics } from "@/lib/api/admin";

export default function AdminSessionEconomicsPage() {
  const [period, setPeriod] = useState(() => currentPeriod());

  const economicsQuery = useQuery({
    queryKey: ["admin", "session-economics", period],
    queryFn: () => getAdminSessionEconomics(period),
  });

  const report = economicsQuery.data;

  return (
    <section data-testid="admin-session-economics" className="space-y-5">
      <div className="flex flex-col gap-3 sm:flex-row sm:items-end sm:justify-between">
        <div>
          <Overline>Owner finance</Overline>
          <p className="mt-1 text-sm text-rally-subtle">
            Session revenue, collections, coach cost, expenses, and expected profit.
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

      {economicsQuery.isError ? (
        <p role="alert" className="rounded-md bg-red-50 p-3 text-sm text-red-700">
          Could not load session economics.
        </p>
      ) : null}

      <div className="grid gap-4 sm:grid-cols-2 xl:grid-cols-4">
        <KpiCard
          label="Expected revenue"
          value={report ? formatCurrency(report.summary.expected_revenue_cents) : loadingValue(economicsQuery.isLoading)}
          detail="Monthly fee multiplied by active enrollments."
        />
        <KpiCard
          label="Paid"
          value={report ? formatCurrency(report.summary.paid_cents) : loadingValue(economicsQuery.isLoading)}
          detail="Attributable collected tuition for these sessions."
        />
        <KpiCard
          label="Yet to pay"
          value={report ? formatCurrency(report.summary.unpaid_cents) : loadingValue(economicsQuery.isLoading)}
          detail="Expected or billed amount still unpaid."
        />
        <KpiCard
          label="Expected profit"
          value={report ? formatCurrency(report.summary.expected_profit_cents) : loadingValue(economicsQuery.isLoading)}
          detail={`Margin ${report ? formatNullablePercent(report.summary.profit_margin) : "pending"}.`}
        />
      </div>

      <div className="grid gap-4 lg:grid-cols-4">
        <MetricStrip label="Coach payroll" value={report ? formatCurrency(report.summary.coach_payroll_cents) : loadingValue(economicsQuery.isLoading)} />
        <MetricStrip label="Rent" value={report ? formatCurrency(report.summary.rent_cents) : loadingValue(economicsQuery.isLoading)} />
        <MetricStrip label="Other expenses" value={report ? formatCurrency(report.summary.other_expenses_cents) : loadingValue(economicsQuery.isLoading)} />
        <MetricStrip label="Sessions" value={report ? formatInteger(report.sessions.length) : loadingValue(economicsQuery.isLoading)} />
      </div>

      {report?.empty_states.length ? (
        <Card p={20}>
          <Overline>Data notes</Overline>
          <ul className="mt-3 space-y-2 text-sm text-rally-subtle">
            {report.empty_states.map((state) => (
              <li key={state}>{state}</li>
            ))}
          </ul>
        </Card>
      ) : null}

      <Card p={0} className="overflow-hidden">
        <div className="border-b border-rally-line px-5 py-4">
          <Overline>Session economics</Overline>
          <p className="mt-1 text-sm text-rally-subtle">
            {formatMonth(period)} revenue and cost by recurring session.
          </p>
        </div>
        <div className="overflow-x-auto">
          <table className="w-full min-w-[1180px] text-left text-sm">
            <thead className="bg-rally-paper text-[11px] uppercase tracking-[0.14em] text-rally-muted">
              <tr>
                <th className="px-5 py-3">Session</th>
                <th className="px-3 py-3">Students</th>
                <th className="px-3 py-3">Monthly fee</th>
                <th className="px-3 py-3">Occurrences</th>
                <th className="px-3 py-3">Revenue / session</th>
                <th className="px-3 py-3">Expected</th>
                <th className="px-3 py-3">Paid</th>
                <th className="px-3 py-3">Yet to pay</th>
                <th className="px-3 py-3">Coach</th>
                <th className="px-3 py-3">Rent</th>
                <th className="px-3 py-3">Other</th>
                <th className="px-5 py-3">Profit</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-rally-line">
              {economicsQuery.isLoading ? (
                <tr>
                  <td className="px-5 py-8 text-rally-subtle" colSpan={12}>
                    Loading session economics...
                  </td>
                </tr>
              ) : report?.sessions.length ? (
                report.sessions.map((session) => (
                  <tr key={session.session_id} className="align-top">
                    <td className="px-5 py-4">
                      <div className="max-w-[260px] font-semibold text-rally-ink">{session.title}</div>
                      <div className="mt-1 text-xs text-rally-muted">
                        {session.coach_name ?? "No coach assigned"}
                      </div>
                    </td>
                    <td className="px-3 py-4">
                      <div className="font-semibold text-rally-ink">
                        {formatInteger(session.active_enrollment_count)}
                      </div>
                      <div className="mt-1 text-xs text-rally-muted">
                        {formatInteger(session.paid_student_count)} paid · {formatInteger(session.unpaid_student_count)} due
                      </div>
                    </td>
                    <NumberCell value={formatCurrency(session.monthly_fee_cents)} />
                    <NumberCell value={formatInteger(session.payable_occurrence_count)} />
                    <NumberCell value={formatCurrency(session.expected_revenue_per_occurrence_cents)} />
                    <NumberCell value={formatCurrency(session.expected_revenue_cents)} strong />
                    <NumberCell value={formatCurrency(session.paid_cents)} tone="good" />
                    <NumberCell value={formatCurrency(session.unpaid_cents)} tone={session.unpaid_cents > 0 ? "warn" : "muted"} />
                    <NumberCell value={formatCurrency(session.coach_payroll_cents)} />
                    <NumberCell value={formatCurrency(session.rent_cents)} />
                    <NumberCell value={formatCurrency(session.other_expenses_cents)} />
                    <td className="px-5 py-4">
                      <div className={session.expected_profit_cents >= 0 ? "font-semibold text-emerald-700" : "font-semibold text-red-700"}>
                        {formatCurrency(session.expected_profit_cents)}
                      </div>
                      <div className="mt-1 text-xs text-rally-muted">
                        {formatNullablePercent(session.profit_margin)}
                      </div>
                    </td>
                  </tr>
                ))
              ) : (
                <tr>
                  <td className="px-5 py-8 text-rally-subtle" colSpan={12}>
                    No session economics found for this month.
                  </td>
                </tr>
              )}
            </tbody>
          </table>
        </div>
      </Card>
    </section>
  );
}

function KpiCard({ label, value, detail }: { label: string; value: string; detail: string }) {
  return (
    <Card p={20} className="flex min-h-[132px] flex-col">
      <Overline>{label}</Overline>
      <BigNum size={28}>{value}</BigNum>
      <p className="mt-2 text-[12px] text-rally-muted">{detail}</p>
    </Card>
  );
}

function MetricStrip({ label, value }: { label: string; value: string }) {
  return (
    <div className="rounded-md border border-rally-line bg-white px-4 py-3 shadow-sm dark:bg-neutral-950">
      <Overline>{label}</Overline>
      <div className="mt-1 text-lg font-semibold text-rally-ink">{value}</div>
    </div>
  );
}

function NumberCell({
  value,
  strong = false,
  tone = "default",
}: {
  value: string;
  strong?: boolean;
  tone?: "default" | "good" | "warn" | "muted";
}) {
  const toneClass =
    tone === "good"
      ? "text-emerald-700"
      : tone === "warn"
        ? "text-amber-700"
        : tone === "muted"
          ? "text-rally-muted"
          : "text-rally-ink";
  return (
    <td className="px-3 py-4">
      <div className={`${strong ? "font-semibold" : "font-medium"} ${toneClass}`}>{value}</div>
    </td>
  );
}

function loadingValue(isLoading: boolean) {
  return isLoading ? "Loading" : "No data";
}

function formatInteger(value: number): string {
  return new Intl.NumberFormat("en-US").format(value);
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

function formatNullablePercent(value: number | null): string {
  return value == null ? "No records" : formatPercent(value);
}

function formatMonth(value: string) {
  const [year, month] = value.split("-").map(Number);
  if (!year || !month) return value;
  return new Intl.DateTimeFormat("en-US", { month: "long", year: "numeric" }).format(
    new Date(year, month - 1, 1),
  );
}

function currentPeriod() {
  const now = new Date();
  return `${now.getFullYear()}-${String(now.getMonth() + 1).padStart(2, "0")}`;
}
