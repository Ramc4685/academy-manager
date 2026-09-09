"use client";

/**
 * The leaving report (issue #698): who left, when, why, and the monthly
 * revenue effect. Owner-only, mirroring the other admin financial reports
 * (see refunds/page.tsx for the pattern this follows).
 */
import { useState } from "react";
import { useQuery } from "@tanstack/react-query";

import { getLeavingReport } from "@/lib/api/v2/departure-policy";
import { Card } from "@/components/ds/card";
import { BigNum, Overline } from "@/components/ds/typography";

function monthStartIso(period: string): string {
  return `${period}-01T00:00:00.000Z`;
}

function monthEndIso(period: string): string {
  const [year, month] = period.split("-").map(Number);
  const next = month === 12 ? `${year + 1}-01` : `${year}-${String(month + 1).padStart(2, "0")}`;
  return monthStartIso(next);
}

const EVENT_LABEL: Record<string, string> = {
  withdrawn: "Dropped",
  dropped: "Dropped",
  deleted: "Deleted",
  hold_reclaimed: "Seat reclaimed",
  hold_expired: "Hold expired",
  hold_reclaim_orphaned: "Reclaimed seat orphaned",
};

export default function AdminLeavingReportPage() {
  const [period, setPeriod] = useState(() => currentPeriod());

  const reportQuery = useQuery({
    queryKey: ["admin", "reports", "leaving", period],
    queryFn: () => getLeavingReport(monthStartIso(period), monthEndIso(period)),
  });

  const report = reportQuery.data;

  return (
    <section data-testid="admin-leaving-report" className="space-y-5">
      <div className="flex flex-col gap-3 sm:flex-row sm:items-end sm:justify-between">
        <div>
          <Overline>Leaving report</Overline>
          <p className="mt-1 text-sm text-rally-subtle">
            Who left, when, why, and the monthly revenue effect for the selected month.
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

      <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
        <Card p={20} className="flex flex-col">
          <Overline>Departures</Overline>
          <BigNum size={28}>
            {report ? String(report.rows.length) : reportQuery.isLoading ? "Loading" : "0"}
          </BigNum>
        </Card>
        <Card p={20} className="flex flex-col">
          <Overline>Monthly revenue effect</Overline>
          <BigNum size={28}>
            {report
              ? formatCurrency(report.total_monthly_revenue_effect_cents)
              : reportQuery.isLoading
                ? "Loading"
                : "$0.00"}
          </BigNum>
        </Card>
        <Card p={20} className="flex flex-col">
          <Overline>System-initiated</Overline>
          <BigNum size={28}>
            {report ? String(report.rows.filter((r) => r.is_system_action).length) : "—"}
          </BigNum>
        </Card>
      </div>

      {reportQuery.isError && (
        <p role="alert" className="rounded-md bg-red-50 p-3 text-sm text-red-700">
          Could not load the leaving report.
        </p>
      )}

      <Card p={24}>
        <Overline>Departures this month</Overline>
        {report?.rows.length ? (
          <div className="mt-4 overflow-x-auto">
            <table className="w-full min-w-[720px] text-left text-sm">
              <thead className="text-xs uppercase text-rally-muted">
                <tr>
                  <th className="px-2 py-2">Date</th>
                  <th className="px-2 py-2">Student</th>
                  <th className="px-2 py-2">Class</th>
                  <th className="px-2 py-2">Type</th>
                  <th className="px-2 py-2">Reason</th>
                  <th className="px-2 py-2">Actor</th>
                  <th className="px-2 py-2">Revenue effect</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-rally-line">
                {report.rows.map((row) => (
                  <tr key={row.event_id}>
                    <td className="px-2 py-2 text-rally-muted">{formatDate(row.occurred_at)}</td>
                    <td className="px-2 py-2 font-medium text-rally-ink">
                      {row.student_name ?? row.student_id}
                    </td>
                    <td className="px-2 py-2 text-rally-muted">{row.session_title ?? "—"}</td>
                    <td className="px-2 py-2 text-rally-ink">
                      {EVENT_LABEL[row.event_type] ?? row.event_type}
                    </td>
                    <td className="px-2 py-2 text-rally-muted">{row.reason ?? "—"}</td>
                    <td className="px-2 py-2 text-rally-muted">
                      {row.is_system_action ? "System" : (row.actor_id ?? "—")}
                    </td>
                    <td className="px-2 py-2 font-medium text-rally-ink">
                      {row.monthly_revenue_effect_cents != null
                        ? formatCurrency(row.monthly_revenue_effect_cents)
                        : "—"}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        ) : (
          <p className="mt-3 text-sm text-rally-subtle">
            {reportQuery.isLoading ? "Loading departures..." : "No departures this month."}
          </p>
        )}
      </Card>
    </section>
  );
}

function formatCurrency(cents: number) {
  return new Intl.NumberFormat("en-US", { style: "currency", currency: "USD" }).format(cents / 100);
}

function formatDate(value: string) {
  const parsed = new Date(value);
  if (Number.isNaN(parsed.getTime())) return value;
  return new Intl.DateTimeFormat("en-US", { dateStyle: "medium" }).format(parsed);
}

function currentPeriod() {
  const now = new Date();
  return `${now.getFullYear()}-${String(now.getMonth() + 1).padStart(2, "0")}`;
}
