"use client";

/**
 * Admin dashboard landing — Rally restyle.
 *
 * Real data only: sessions today + monthly revenue + recent payments.
 * Recharts is dynamic-imported to keep the admin landing chunk small.
 *
 * Intentionally no "Needs your attention" section — backend has no
 * attention endpoint yet. See plan Phase 6/follow-on.
 */

import dynamic from "next/dynamic";
import { useQuery } from "@tanstack/react-query";

import { listAdminSessions, listAdminPayments, getRevenue } from "@/lib/api/admin";
import type { PaymentStatus } from "@/lib/api/admin";
import { queryKeys } from "@/lib/query/keys";

import { Card } from "@/components/ds/card";
import { Chip, type ChipVariant } from "@/components/ds/chip";
import { LaneHeader } from "@/components/ds/lane";
import { BigNum, Overline } from "@/components/ds/typography";

const RevenueChart = dynamic(() => import("@/components/admin/RevenueChart"), {
  ssr: false,
  loading: () => <div className="h-48 animate-pulse rounded-xl bg-rally-line/40" />,
});

function todayISO(): string {
  return new Date().toISOString().slice(0, 10);
}

function currentMonthKey(): string {
  return new Date().toISOString().slice(0, 7);
}

function formatCents(cents: number): string {
  return new Intl.NumberFormat("en-US", {
    style: "currency",
    currency: "USD",
    maximumFractionDigits: 0,
  }).format(cents / 100);
}

const PAYMENT_CHIP: Record<PaymentStatus, ChipVariant> = {
  succeeded: "paid",
  pending: "pending",
  refunded: "refunded",
  partially_refunded: "partial",
  failed: "failed",
  expired: "expired",
};

const PAYMENT_LABEL: Record<PaymentStatus, string> = {
  succeeded: "PAID",
  pending: "PENDING",
  refunded: "REFUNDED",
  partially_refunded: "PARTIAL",
  failed: "FAILED",
  expired: "EXPIRED",
};

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

  // Normalize once. Treat absent/partial responses as empty rather than
  // sprinkling optional chains throughout the JSX.
  const sessions = sessionsQuery.data?.sessions ?? [];
  const payments = paymentsQuery.data?.payments ?? [];
  const revenueByMonth = revenueQuery.data?.by_month ?? {};

  const todayCount = sessions.length;
  const paymentsTracked = payments.length;
  const monthRevenue = revenueByMonth[currentMonthKey()] ?? 0;

  const recentPayments = payments
    .slice()
    .sort((a, b) => new Date(b.created_at).getTime() - new Date(a.created_at).getTime())
    .slice(0, 5);

  const chartData = (Object.entries(revenueByMonth) as Array<[string, number]>)
    .sort(([a], [b]) => a.localeCompare(b))
    .slice(-6)
    .map(([month, cents]) => ({ month, revenue: cents / 100 }));

  return (
    <section data-testid="admin-dashboard" className="space-y-6">
      {/* KPI strip */}
      <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-4">
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
          label="Payments tracked"
          value={paymentsQuery.isLoading ? "—" : String(paymentsTracked)}
          loading={paymentsQuery.isLoading}
        />
      </div>

      {/* Revenue chart */}
      <Card p={20}>
        <LaneHeader index="01" title="Monthly revenue (last 6 months)" />
        {revenueQuery.isLoading ? (
          <div className="h-48 animate-pulse rounded-xl bg-rally-line/40" />
        ) : chartData.length > 0 ? (
          <RevenueChart data={chartData} />
        ) : (
          <EmptyState message="No revenue data yet." />
        )}
      </Card>

      {/* Recent payments */}
      <Card p={20}>
        <LaneHeader index="02" title="Recent payments" />
        {paymentsQuery.isLoading ? (
          <TableSkeleton rows={3} />
        ) : recentPayments.length === 0 ? (
          <EmptyState message="No payments yet." />
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full text-sm" data-testid="admin-dashboard-recent-payments">
              <thead>
                <tr className="border-b border-rally-line text-left">
                  <th className="pb-2 pr-4 font-mono text-[10px] font-bold uppercase tracking-overline text-rally-muted">
                    ID
                  </th>
                  <th className="pb-2 pr-4 font-mono text-[10px] font-bold uppercase tracking-overline text-rally-muted">
                    Amount
                  </th>
                  <th className="pb-2 pr-4 font-mono text-[10px] font-bold uppercase tracking-overline text-rally-muted">
                    Status
                  </th>
                  <th className="pb-2 font-mono text-[10px] font-bold uppercase tracking-overline text-rally-muted">
                    Date
                  </th>
                </tr>
              </thead>
              <tbody>
                {recentPayments.map((p) => {
                  const variant = PAYMENT_CHIP[p.status];
                  const label = PAYMENT_LABEL[p.status];
                  return (
                    <tr key={p.payment_id} className="border-b border-rally-line/60 last:border-0">
                      <td className="py-2.5 pr-4 font-mono text-xs text-rally-muted">
                        {p.payment_id.slice(0, 8)}…
                      </td>
                      <td className="py-2.5 pr-4 font-mono font-semibold tabular-nums text-rally-ink">
                        {formatCents(p.amount_cents)}
                      </td>
                      <td className="py-2.5 pr-4">
                        <Chip variant={variant} label={label} />
                      </td>
                      <td className="py-2.5 text-rally-muted">
                        {new Date(p.created_at).toLocaleDateString()}
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        )}
      </Card>
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
    <Card p={20}>
      <Overline>{label}</Overline>
      {loading ? (
        <div className="mt-2 h-9 w-28 animate-pulse rounded bg-rally-line/40" />
      ) : (
        <div className="mt-1.5">
          <BigNum size={32}>{value}</BigNum>
        </div>
      )}
    </Card>
  );
}

function EmptyState({ message }: { message: string }) {
  return <p className="text-sm text-rally-subtle">{message}</p>;
}

function TableSkeleton({ rows }: { rows: number }) {
  return (
    <ul className="space-y-2">
      {Array.from({ length: rows }).map((_, i) => (
        <li key={i} className="h-9 animate-pulse rounded bg-rally-line/40" />
      ))}
    </ul>
  );
}
