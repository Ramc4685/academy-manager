"use client";

import { useState } from "react";
import { useMutation, useQuery } from "@tanstack/react-query";
import { AlertTriangle, ArrowDownRight, ArrowUpRight, Minus } from "lucide-react";

import { exportAdminReportCsv, getRevenue } from "@/lib/api/admin";
import {
  listReportSnapshots,
  type ReportSnapshotCard,
} from "@/lib/api/v2/reports";
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
      <SnapshotsBlock />

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

// ────────────────────────────────────────────────────────────────────────────
// Snapshot cards (Wave 5 — placeholders pending Agent A read models).
// ────────────────────────────────────────────────────────────────────────────

function SnapshotsBlock() {
  const snapshotsQuery = useQuery({
    queryKey: ["admin", "reports", "snapshots"],
    queryFn: listReportSnapshots,
  });

  const cards = snapshotsQuery.data ?? [];

  return (
    <div className="space-y-3" data-testid="admin-reports-snapshots">
      <div
        role="status"
        className="flex items-start gap-2 rounded-md border border-amber-200 bg-amber-50 px-3 py-2 text-sm text-amber-900"
      >
        <AlertTriangle className="size-4 mt-0.5 shrink-0" aria-hidden="true" />
        <div>
          <strong className="font-semibold">Snapshots are placeholder.</strong>{" "}
          Pre-computed reporting read models are in flight (Wave 5 Agent A).
          These cards will populate as the read-model endpoints land.
        </div>
      </div>
      <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
        {snapshotsQuery.isPending
          ? Array.from({ length: 4 }, (_, i) => (
              <div key={i} className="h-32 animate-pulse rounded-xl bg-neutral-100" />
            ))
          : cards.map((card) => <SnapshotCard key={card.key} card={card} />)}
      </div>
    </div>
  );
}

function SnapshotCard({ card }: { card: ReportSnapshotCard }) {
  return (
    <Card p={20} className="flex flex-col" data-testid={`admin-reports-snapshot-${card.key}`}>
      <Overline>{card.label}</Overline>
      <div className="mt-2 flex items-baseline gap-2">
        <BigNum size={28}>{card.value}</BigNum>
        {card.delta && (
          <span
            className={`inline-flex items-center gap-0.5 font-mono text-[11px] font-bold ${
              card.trend === "up"
                ? "text-emerald-700"
                : card.trend === "down"
                  ? "text-red-700"
                  : "text-rally-muted"
            }`}
            aria-label={`Change vs prior period: ${card.delta}`}
          >
            <TrendIcon trend={card.trend ?? "flat"} />
            {card.delta}
          </span>
        )}
      </div>
      <p className="mt-2 text-[12px] text-rally-muted">{card.description}</p>
    </Card>
  );
}

function TrendIcon({ trend }: { trend: "up" | "down" | "flat" }) {
  if (trend === "up") return <ArrowUpRight className="size-3" aria-hidden="true" />;
  if (trend === "down") return <ArrowDownRight className="size-3" aria-hidden="true" />;
  return <Minus className="size-3" aria-hidden="true" />;
}
