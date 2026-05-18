"use client";

import { useState } from "react";
import { useMutation } from "@tanstack/react-query";

import { exportAdminReportCsv } from "@/lib/api/admin";

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
  const exportMutation = useMutation({
    mutationFn: async (report: (typeof REPORTS)[number]) => {
      const csv = await exportAdminReportCsv(report.name);
      return { title: report.title, csv };
    },
    onSuccess: setPreview,
  });

  return (
    <section data-testid="admin-reports" className="space-y-5">
      <div>
        <h1 className="text-2xl font-semibold">Reports</h1>
        <p className="mt-1 text-sm text-neutral-500">
          CSV exports served by the admin BFF with the current Firebase token.
        </p>
      </div>

      <div className="grid gap-3 lg:grid-cols-3">
        {REPORTS.map((report) => (
          <article
            key={report.name}
            className="rounded-lg border border-neutral-200 bg-white p-4 dark:border-neutral-800 dark:bg-neutral-900"
          >
            <h2 className="font-semibold">{report.title}</h2>
            <p className="mt-1 min-h-10 text-sm text-neutral-500">{report.description}</p>
            <button
              type="button"
              onClick={() => exportMutation.mutate(report)}
              disabled={exportMutation.isPending}
              className="mt-4 min-h-touch rounded-md border border-blue-300 px-3 text-sm font-medium text-blue-700 hover:bg-blue-50 disabled:opacity-60 dark:border-blue-700 dark:text-blue-300"
            >
              Export CSV
            </button>
          </article>
        ))}
      </div>

      {exportMutation.isError && (
        <p role="alert" className="rounded-md bg-red-50 p-3 text-sm text-red-700">
          Could not export that report.
        </p>
      )}

      {preview && (
        <section className="rounded-lg border border-neutral-200 bg-white p-4 dark:border-neutral-800 dark:bg-neutral-900">
          <div className="flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between">
            <h2 className="text-lg font-semibold">{preview.title} preview</h2>
            <button
              type="button"
              onClick={() => downloadCsv(preview.title, preview.csv)}
              className="min-h-touch rounded-md bg-blue-600 px-4 text-sm font-medium text-white hover:bg-blue-700"
            >
              Download
            </button>
          </div>
          <pre className="mt-4 max-h-80 overflow-auto rounded-md bg-neutral-950 p-3 text-xs text-neutral-100">
            {preview.csv}
          </pre>
        </section>
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
