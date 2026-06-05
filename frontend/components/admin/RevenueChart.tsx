"use client";

import type { ReactNode } from "react";

/**
 * RevenueChart — Recharts BarChart, dynamically imported by admin pages.
 *
 * Only this file imports from "recharts". All admin pages use:
 *   const RevenueChart = dynamic(() => import("@/components/admin/RevenueChart"), { ssr: false })
 *
 * This ensures Recharts (~150 KB) is excluded from the admin landing chunk.
 */

import {
  BarChart,
  Bar,
  XAxis,
  YAxis,
  Tooltip,
  ResponsiveContainer,
  CartesianGrid,
} from "recharts";

export interface RevenueDataPoint {
  month: string; // e.g. "2025-01"
  revenue: number; // dollars (already divided by 100)
}

function formatCurrency(value: unknown) {
  const numericValue = typeof value === "number" ? value : Number(value ?? 0);
  return new Intl.NumberFormat("en-US", { style: "currency", currency: "USD" }).format(
    Number.isFinite(numericValue) ? numericValue : 0,
  );
}

export default function RevenueChart({ data }: { data: RevenueDataPoint[] }) {
  return (
    <ResponsiveContainer width="100%" height={192}>
      <BarChart data={data} margin={{ top: 4, right: 8, left: 0, bottom: 0 }}>
        <CartesianGrid strokeDasharray="3 3" className="stroke-neutral-200 dark:stroke-neutral-700" />
        <XAxis
          dataKey="month"
          tick={{ fontSize: 11 }}
          tickFormatter={(v: string) => {
            const [, m] = v.split("-");
            return new Date(2000, parseInt(m, 10) - 1).toLocaleString("default", {
              month: "short",
            });
          }}
        />
        <YAxis
          tick={{ fontSize: 11 }}
          tickFormatter={(v: number) =>
            v >= 1000 ? `$${(v / 1000).toFixed(0)}k` : `$${v}`
          }
          width={40}
        />
        <Tooltip
          formatter={(value: unknown) => formatCurrency(value)}
          labelFormatter={(label: ReactNode) => String(label ?? "")}
        />
        <Bar dataKey="revenue" fill="#2563eb" radius={[4, 4, 0, 0]} />
      </BarChart>
    </ResponsiveContainer>
  );
}
