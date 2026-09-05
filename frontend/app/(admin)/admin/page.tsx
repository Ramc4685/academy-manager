"use client";

/**
 * Admin dashboard landing — Rally restyle.
 *
 * Real data only: sessions today + monthly revenue + collections totals
 * (owed / autopay scheduled / needs action) + recent payments + dashboard
 * attention BFF signals.
 * Recharts is dynamic-imported to keep the admin landing chunk small.
 */

import dynamic from "next/dynamic";
import Link from "next/link";
import { useQuery } from "@tanstack/react-query";

import {
  listAdminSessions,
  getAdminCollections,
  getAdminPaymentFeed,
  getRevenue,
  listAdminAttention,
} from "@/lib/api/admin";
import type { AdminAttentionSeverity } from "@/lib/api/admin";
import { formatCents } from "@/lib/money";
import { queryKeys } from "@/lib/query/keys";
import { paymentMethodLabel, statusChip } from "@/app/(admin)/admin/payments/format";
import { normalizeCollections } from "@/app/(admin)/admin/payments/buckets/bucket-view";

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

function prevMonthKey(): string {
  const d = new Date();
  d.setUTCDate(1);
  d.setUTCMonth(d.getUTCMonth() - 1);
  return d.toISOString().slice(0, 7);
}

const RECENT_PAYMENTS_LIMIT = 5;

export default function AdminDashboardPage() {
  const today = todayISO();

  const sessionsQuery = useQuery({
    queryKey: queryKeys.admin.sessions(today),
    queryFn: () => listAdminSessions(today),
  });

  // Money tiles read the same six-bucket view as the Payments page, so the
  // dashboard and the bucket list can never disagree about who owes what.
  // "current" is the key for the unpinned (this month) period.
  const collectionsQuery = useQuery({
    queryKey: queryKeys.admin.collections("current"),
    queryFn: () => getAdminCollections(),
  });

  // INVARIANT (PR #645): "Recent payments" MUST read the paid-only feed, not
  // listAdminPayments(). The list is invoice-centric — Stripe/Zelle settlements
  // are folded into invoice rows dated by invoice creation, and expired/failed
  // attempts sit alongside real money. Sorting that list by created_at hid every
  // Stripe payment behind registration checkouts (the prod defect). The feed
  // returns money actually received, newest settlement first.
  const paymentFeedQuery = useQuery({
    queryKey: queryKeys.admin.paymentFeed(RECENT_PAYMENTS_LIMIT),
    queryFn: () => getAdminPaymentFeed(RECENT_PAYMENTS_LIMIT),
  });

  const revenueQuery = useQuery({
    queryKey: queryKeys.admin.revenue(),
    queryFn: () => getRevenue(),
  });

  const attentionQuery = useQuery({
    queryKey: queryKeys.admin.attention(),
    queryFn: () => listAdminAttention(),
  });

  // Normalize once. Treat absent/partial responses as empty rather than
  // sprinkling optional chains throughout the JSX.
  // `normalizeCollections` also absorbs e2e stubs that answer every
  // `/admin/payments*` URL with `{ payments: [] }` — the tiles render zeros.
  const sessions = sessionsQuery.data?.sessions ?? [];
  const collectionsTotals = normalizeCollections(collectionsQuery.data).totals;
  const revenueByMonth = revenueQuery.data?.by_month ?? {};

  const todayCount = sessions.length;
  const monthRevenue = revenueByMonth[currentMonthKey()] ?? 0;

  const recentPayments = (paymentFeedQuery.data?.payments ?? []).slice(0, RECENT_PAYMENTS_LIMIT);

  const chartData = (Object.entries(revenueByMonth) as Array<[string, number]>)
    .sort(([a], [b]) => a.localeCompare(b))
    .slice(-6)
    .map(([month, cents]) => ({ month, revenue: cents / 100 }));

  return (
    <section data-testid="admin-dashboard" className="space-y-6">
      {/* KPI strip */}
      <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-5 gap-4">
        <KpiCard
          label="Sessions today"
          value={sessionsQuery.isLoading ? "—" : String(todayCount)}
          loading={sessionsQuery.isLoading}
        />
        <KpiCard
          label="Revenue (month to date)"
          value={revenueQuery.isLoading ? "—" : formatCents(monthRevenue, { whole: true })}
          loading={revenueQuery.isLoading}
          hint={
            revenueQuery.isLoading
              ? undefined
              : `Last month ${formatCents(revenueByMonth[prevMonthKey()] ?? 0, { whole: true })}`
          }
        />
        <Link
          href="/admin/payments#bucket-past_due"
          className="block rounded-xl focus:outline-none focus-visible:ring-2 focus-visible:ring-rally-cobalt"
          data-testid="dashboard-tile-owed"
        >
          <KpiCard
            label="Owed this month"
            value={collectionsQuery.isLoading ? "—" : formatCents(collectionsTotals.owed_cents)}
            loading={collectionsQuery.isLoading}
          />
        </Link>
        <Link
          href="/admin/payments#bucket-autopay_scheduled"
          className="block rounded-xl focus:outline-none focus-visible:ring-2 focus-visible:ring-rally-cobalt"
          data-testid="dashboard-tile-autopay"
        >
          <KpiCard
            label="Autopay scheduled"
            value={
              collectionsQuery.isLoading
                ? "—"
                : formatCents(collectionsTotals.autopay_scheduled_cents)
            }
            loading={collectionsQuery.isLoading}
            hint={
              collectionsQuery.isLoading
                ? undefined
                : `${collectionsTotals.autopay_scheduled_count} ${
                    collectionsTotals.autopay_scheduled_count === 1 ? "family" : "families"
                  }`
            }
          />
        </Link>
        <Link
          href="/admin/payments#bucket-failed_autopay"
          className="block rounded-xl focus:outline-none focus-visible:ring-2 focus-visible:ring-rally-cobalt"
          data-testid="dashboard-tile-needs-action"
        >
          <KpiCard
            label="Needs action"
            value={
              collectionsQuery.isLoading ? "—" : String(collectionsTotals.needs_action_count)
            }
            loading={collectionsQuery.isLoading}
            hint={collectionsQuery.isLoading ? undefined : "failed autopay · past due"}
          />
        </Link>
      </div>

      <Card p={20}>
        <LaneHeader index="00" title="Needs your attention" />
        {attentionQuery.isLoading ? (
          <TableSkeleton rows={3} />
        ) : attentionQuery.isError ? (
          <EmptyState message="Attention signals are unavailable right now." />
        ) : (attentionQuery.data?.items ?? []).length > 0 ? (
          <div className="grid gap-3 lg:grid-cols-2" data-testid="admin-dashboard-attention">
            {(attentionQuery.data?.items ?? []).map((item) => (
              <a
                key={item.attention_id}
                href={item.href}
                className="group rounded-lg border border-rally-line bg-white p-4 transition hover:border-rally-cobalt hover:bg-rally-paper"
              >
                <div className="flex items-start justify-between gap-4">
                  <div className="min-w-0">
                    <Chip variant={attentionChip(item.severity)} label={item.severity.toUpperCase()} />
                    <h3 className="mt-3 font-display text-[17px] font-semibold text-rally-ink">
                      {item.title}
                    </h3>
                    <p className="mt-1 text-sm leading-5 text-rally-muted">{item.detail}</p>
                  </div>
                  <span className="font-mono text-[24px] font-bold tabular-nums text-rally-ink">
                    {item.count}
                  </span>
                </div>
              </a>
            ))}
          </div>
        ) : (
          <EmptyState message="No attention items right now." />
        )}
      </Card>

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
        {paymentFeedQuery.isLoading ? (
          <TableSkeleton rows={3} />
        ) : recentPayments.length === 0 ? (
          <EmptyState message="No payments received yet." />
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full text-sm" data-testid="admin-dashboard-recent-payments">
              <thead>
                <tr className="border-b border-rally-line text-left">
                  <th className="pb-2 pr-4 font-mono text-[10px] font-bold uppercase tracking-overline text-rally-muted">
                    Payment
                  </th>
                  <th className="pb-2 pr-4 font-mono text-[10px] font-bold uppercase tracking-overline text-rally-muted">
                    Amount
                  </th>
                  <th className="pb-2 pr-4 font-mono text-[10px] font-bold uppercase tracking-overline text-rally-muted">
                    Status
                  </th>
                  <th className="pb-2 pr-4 font-mono text-[10px] font-bold uppercase tracking-overline text-rally-muted">
                    Method
                  </th>
                  <th className="pb-2 font-mono text-[10px] font-bold uppercase tracking-overline text-rally-muted">
                    Paid on
                  </th>
                </tr>
              </thead>
              <tbody>
                {recentPayments.map((p) => {
                  const chip = statusChip(p.status);
                  const method = paymentMethodLabel(p.payment_method);
                  const netCents = Math.max(p.amount_cents - p.refunded_cents, 0);
                  return (
                    <tr key={p.payment_id} className="border-b border-rally-line/60 last:border-0">
                      <td className="py-2.5 pr-4">
                        <div className="font-medium text-rally-ink">
                          {p.parent_name ?? "Family on file"}
                        </div>
                        {p.refunded_cents > 0 && (
                          <div className="mt-0.5 text-xs text-rally-muted">
                            {formatCents(p.refunded_cents)} refunded
                          </div>
                        )}
                      </td>
                      <td className="py-2.5 pr-4 font-mono font-semibold tabular-nums text-rally-ink">
                        {formatCents(netCents)}
                      </td>
                      <td className="py-2.5 pr-4">
                        <Chip variant={chip.variant} label={chip.label} />
                      </td>
                      <td className="py-2.5 pr-4">
                        {method ? (
                          <Chip variant={method === "STRIPE" ? "autopayOn" : "manual"} label={method} />
                        ) : (
                          <span className="text-rally-subtle">—</span>
                        )}
                      </td>
                      <td className="py-2.5 text-rally-muted">
                        {new Date(p.paid_at).toLocaleDateString()}
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

function attentionChip(severity: AdminAttentionSeverity): ChipVariant {
  if (severity === "high") return "failed";
  if (severity === "medium") return "pending";
  return "open";
}

function KpiCard({
  label,
  value,
  loading,
  hint,
}: {
  label: string;
  value: string;
  loading: boolean;
  hint?: string;
}) {
  return (
    <Card p={20}>
      <Overline>{label}</Overline>
      {loading ? (
        <div className="mt-2 h-9 w-28 animate-pulse rounded bg-rally-line/40" />
      ) : (
        <div className="mt-1.5">
          <BigNum size={32}>{value}</BigNum>
          {hint && <p className="mt-1 text-xs text-rally-muted">{hint}</p>}
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
