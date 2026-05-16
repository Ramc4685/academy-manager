"use client";

/**
 * Admin dashboard landing.
 *
 * Shows today's session count, current-month revenue total, recent payments,
 * and a dynamically-imported Recharts bar chart of monthly revenue.
 * Recharts is NOT statically imported — it is code-split via dynamic() to
 * keep the admin landing chunk under 300 KB.
 */

import dynamic from "next/dynamic";
import { useQuery } from "@tanstack/react-query";

import { listAdminSessions, listAdminPayments, getRevenue } from "@/lib/api/admin";
import { queryKeys } from "@/lib/query/keys";

// Dynamic import: Recharts only loads when the revenue chart renders.
const RevenueChart = dynamic(() => import("@/components/admin/RevenueChart"), {
  ssr: false,
  loading: () => (
    <div className="h-48 animate-pulse rounded-lg bg-neutral-100 dark:bg-neutral-800" />
  ),
});

function todayISO(): string {
  return new Date().toISOString().slice(0, 10);
}

function currentMonthKey(): string {
  return new Date().toISOString().slice(0, 7); // "YYYY-MM"
}

function formatCents(cents: number): string {
  return new Intl.NumberFormat("en-US", { style: "currency", currency: "USD" }).format(cents / 100);
}

export default function AdminDashboardPage() {
  const today = todayISO();

  const sessionsQuery = useQuery({
    queryKey: queryKeys.admin.sessions(today),
    queryFn: () => listAdminSessions(today),
  });

  const paymentsQuery = useQuery({
    queryKey: queryKeys.admin.payments(),
    queryFn: () => listAdminPayments(),
  });

  const revenueQuery = useQuery({
    queryKey: queryKeys.admin.revenue(),
    queryFn: () => getRevenue(),
  });

  const todayCount = sessionsQuery.data?.sessions.length ?? 0;
  const monthRevenue = revenueQuery.data?.by_month[currentMonthKey()] ?? 0;

  const recentPayments = (paymentsQuery.data?.payments ?? [])
    .slice()
    .sort((a, b) => new Date(b.created_at).getTime() - new Date(a.created_at).getTime())
    .slice(0, 5);

  // Prepare bar chart data from by_month — last 6 months
  const chartData = Object.entries(revenueQuery.data?.by_month ?? {})
    .sort(([a], [b]) => a.localeCompare(b))
    .slice(-6)
    .map(([month, cents]) => ({ month, revenue: cents / 100 }));

  return (
    <section data-testid="admin-dashboard">
      <h1 className="text-2xl font-semibold mb-6">Dashboard</h1>

      {/* KPI cards */}
      <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-4 mb-8">
        <KpiCard
          label="Sessions today"
          value={sessionsQuery.isLoading ? "—" : String(todayCount)}
          loading={sessionsQuery.isLoading}
        />
        <KpiCard
          label="Revenue this month"
          value={revenueQuery.isLoading ? "—" : formatCents(monthRevenue)}
          loading={revenueQuery.isLoading}
        />
        <KpiCard
          label="Recent payments"
          value={paymentsQuery.isLoading ? "—" : String(paymentsQuery.data?.payments.length ?? 0)}
          loading={paymentsQuery.isLoading}
        />
      </div>

      {/* Monthly revenue chart */}
      <div className="rounded-lg border border-neutral-200 dark:border-neutral-800 bg-white dark:bg-neutral-900 p-4 mb-8">
        <h2 className="text-sm font-semibold text-neutral-600 dark:text-neutral-400 mb-3">
          Monthly revenue (last 6 months)
        </h2>
        {revenueQuery.isLoading ? (
          <div className="h-48 animate-pulse rounded-lg bg-neutral-100 dark:bg-neutral-800" />
        ) : chartData.length > 0 ? (
          <RevenueChart data={chartData} />
        ) : (
          <p className="text-sm text-neutral-400">No revenue data yet.</p>
        )}
      </div>

      {/* Recent payments table */}
      <div className="rounded-lg border border-neutral-200 dark:border-neutral-800 bg-white dark:bg-neutral-900 p-4">
        <h2 className="text-sm font-semibold text-neutral-600 dark:text-neutral-400 mb-3">
          Recent payments
        </h2>
        {paymentsQuery.isLoading ? (
          <TableSkeleton rows={3} />
        ) : recentPayments.length === 0 ? (
          <p className="text-sm text-neutral-400">No payments yet.</p>
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead>
                <tr className="border-b border-neutral-200 dark:border-neutral-700 text-left text-neutral-500">
                  <th className="pb-2 pr-4 font-medium">ID</th>
                  <th className="pb-2 pr-4 font-medium">Amount</th>
                  <th className="pb-2 pr-4 font-medium">Status</th>
                  <th className="pb-2 font-medium">Date</th>
                </tr>
              </thead>
              <tbody>
                {recentPayments.map((p) => (
                  <tr
                    key={p.payment_id}
                    className="border-b border-neutral-100 dark:border-neutral-800 last:border-0"
                  >
                    <td className="py-2 pr-4 font-mono text-xs text-neutral-500">
                      {p.payment_id.slice(0, 8)}…
                    </td>
                    <td className="py-2 pr-4 tabular-nums">{formatCents(p.amount_cents)}</td>
                    <td className="py-2 pr-4">
                      <StatusBadge status={p.status} />
                    </td>
                    <td className="py-2 text-neutral-500">
                      {new Date(p.created_at).toLocaleDateString()}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </div>
    </section>
  );
}

function KpiCard({
  label,
  value,
  loading,
}: {
  label: string;
  value: string;
  loading: boolean;
}) {
  return (
    <div className="rounded-lg border border-neutral-200 dark:border-neutral-800 bg-white dark:bg-neutral-900 p-4">
      <p className="text-xs font-medium text-neutral-500 uppercase tracking-wide">{label}</p>
      {loading ? (
        <div className="mt-2 h-7 w-24 animate-pulse rounded bg-neutral-100 dark:bg-neutral-800" />
      ) : (
        <p className="mt-1 text-2xl font-semibold tabular-nums">{value}</p>
      )}
    </div>
  );
}

function StatusBadge({ status }: { status: string }) {
  const colors: Record<string, string> = {
    succeeded: "bg-green-100 text-green-800 dark:bg-green-900 dark:text-green-200",
    pending: "bg-amber-100 text-amber-800 dark:bg-amber-900 dark:text-amber-200",
    refunded: "bg-neutral-100 text-neutral-600 dark:bg-neutral-800 dark:text-neutral-300",
    partially_refunded: "bg-blue-100 text-blue-800 dark:bg-blue-900 dark:text-blue-200",
    failed: "bg-red-100 text-red-800 dark:bg-red-900 dark:text-red-200",
  };
  return (
    <span
      className={`inline-block rounded-full px-2 py-0.5 text-xs font-medium ${
        colors[status] ?? "bg-neutral-100 text-neutral-600"
      }`}
    >
      {status}
    </span>
  );
}

function TableSkeleton({ rows }: { rows: number }) {
  return (
    <ul className="space-y-2">
      {Array.from({ length: rows }).map((_, i) => (
        <li key={i} className="h-9 animate-pulse rounded bg-neutral-100 dark:bg-neutral-800" />
      ))}
    </ul>
  );
}
