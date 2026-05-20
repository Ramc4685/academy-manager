"use client";

import { useState } from "react";
import { useMutation, useQuery } from "@tanstack/react-query";

import { exportAdminReportCsv, getRevenue } from "@/lib/api/admin";
import { Card } from "@/components/ds/card";
import { Button } from "@/components/ds/button";
import { MiniBars } from "@/components/ds/charts";
import { BigNum, Overline } from "@/components/ds/typography";

const REPORTS = [
  {
    name: "pending-payments",
    title: "Pending payments",
    description: "Manual invoices still waiting for payment.",
  },
  {
    name: "revenue",
    title: "Revenue",
    description: "Collected revenue by month from the billing context.",
  },
  {
    name: "attendance",
    title: "Attendance",
    description: "Recent attendance marks from the coaching context.",
  },
] as const;

export default function AdminReportsPage() {
  const [preview, setPreview] = useState<{ title: string; csv: string } | null>(null);

  const revenueQuery = useQuery({
    queryKey: ["admin", "revenue"],
    queryFn: getRevenue,
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
  const chartValues = last6Months.length > 0 ? last6Months.map(m => revenueByMonth[m]) : [0, 0, 0, 0, 0, 0];

  return (
    <section data-testid="admin-reports" className="space-y-5">


      <div className="grid gap-4 lg:grid-cols-3">
        <div className="lg:col-span-3">
          <Card p={24} className="flex flex-col sm:flex-row sm:items-center justify-between gap-6">
            <div>
              <Overline>Revenue Trend (Last 6 Months)</Overline>
              <div className="mt-2">
                <BigNum size={32}>
                  {new Intl.NumberFormat("en-US", { style: "currency", currency: "USD" }).format(
                    (chartValues[chartValues.length - 1] ?? 0) / 100
                  )}
                </BigNum>
              </div>
              <p className="text-sm text-neutral-500 mt-1">Latest month shown</p>
            </div>
            {revenueQuery.isLoading ? (
              <div className="h-20 w-60 animate-pulse rounded-md bg-neutral-100 dark:bg-neutral-800" />
            ) : (
              <div className="shrink-0">
                <MiniBars values={chartValues} w={240} h={80} highlight={chartValues.length - 1} />
              </div>
            )}
          </Card>
        </div>

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

function downloadCsv(title: string, csv: string) {
  const blob = new Blob([csv], { type: "text/csv;charset=utf-8" });
  const url = URL.createObjectURL(blob);
  const anchor = document.createElement("a");
  anchor.href = url;
  anchor.download = `${title.toLowerCase().replace(/\s+/g, "-")}.csv`;
  anchor.click();
  URL.revokeObjectURL(url);
}
