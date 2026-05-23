"use client";

import { useState } from "react";
import { useMutation, useQuery } from "@tanstack/react-query";

import { exportAdminReportCsv, getAdminReportKpis, getRevenue } from "@/lib/api/admin";
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

  const revenueQuery = useQuery({
    queryKey: ["admin", "revenue"],
    queryFn: getRevenue,
  });

  const kpiQuery = useQuery({
    queryKey: ["admin", "reports", "kpis"],
    queryFn: getAdminReportKpis,
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
  const kpis = kpiQuery.data;

  return (
    <section data-testid="admin-reports" className="space-y-5">
      <div className="space-y-3">
        <Overline>Dashboard</Overline>
        <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
          <KpiCard
            label="Active students"
            value={kpis ? formatInteger(kpis.active_students) : kpiQuery.isLoading ? "Loading" : "No data"}
            description="Students with at least one active enrollment."
          />
          <KpiCard
            label="Attendance rate (30d)"
            value={kpis ? formatPercent(kpis.attendance_rate_30d) : kpiQuery.isLoading ? "Loading" : "No data"}
            description="Present or late attendance marks across the last 30 days."
          />
          <KpiCard
            label="Dues collected (MTD)"
            value={kpis ? formatCurrency(kpis.dues_collected_mtd_cents) : kpiQuery.isLoading ? "Loading" : "No data"}
            description="Paid tuition and dues recorded for the current month."
          />
          <KpiCard
            label="Pending waivers"
            value={kpis ? formatInteger(kpis.pending_waivers) : kpiQuery.isLoading ? "Loading" : "No data"}
            description="Active students without a current signed waiver record."
          />
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

function formatCurrency(cents: number) {
  return new Intl.NumberFormat("en-US", { style: "currency", currency: "USD" }).format(cents / 100);
}

function formatMonth(value: string) {
  const [year, month] = value.split("-").map(Number);
  if (!year || !month) return value;
  return new Intl.DateTimeFormat("en-US", { month: "short", year: "numeric" }).format(
    new Date(year, month - 1, 1),
  );
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
