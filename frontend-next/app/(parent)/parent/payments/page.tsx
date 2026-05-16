"use client";

import { useQuery } from "@tanstack/react-query";

import { listParentPayments } from "@/lib/api/parent";

export default function ParentPaymentsPage() {
  const { data, isLoading, isError } = useQuery({
    queryKey: ["parent", "payments"],
    queryFn: listParentPayments,
  });

  if (isLoading) return <p>Loading…</p>;
  if (isError) return <p className="text-red-600">Could not load payments.</p>;
  const payments = data?.payments ?? [];

  return (
    <section data-testid="parent-payments">
      <h1 className="mb-4 text-2xl font-semibold">Payments</h1>
      {payments.length === 0 && (
        <p className="text-neutral-500">No payments yet.</p>
      )}
      <ul className="space-y-3" data-testid="payments-list">
        {payments.map((p) => (
          <li
            key={p.payment_id}
            data-testid={`payment-${p.payment_id}`}
            className="rounded-lg border border-neutral-200 p-4 dark:border-neutral-800"
          >
            <div className="flex items-center justify-between">
              <p className="font-medium">
                {(p.amount_cents / 100).toLocaleString(undefined, {
                  style: "currency",
                  currency: p.currency.toUpperCase(),
                })}
              </p>
              <StatusBadge status={p.status} />
            </div>
            <p className="mt-1 text-xs text-neutral-500">
              {new Date(p.created_at).toLocaleString()}
            </p>
            {p.refunded_cents > 0 && (
              <p className="text-xs text-amber-700 dark:text-amber-300">
                Refunded {(p.refunded_cents / 100).toLocaleString(undefined, {
                  style: "currency",
                  currency: p.currency.toUpperCase(),
                })}
              </p>
            )}
          </li>
        ))}
      </ul>
    </section>
  );
}

function StatusBadge({ status }: { status: string }) {
  const palette: Record<string, string> = {
    succeeded: "bg-emerald-100 text-emerald-800 dark:bg-emerald-900 dark:text-emerald-100",
    pending: "bg-amber-100 text-amber-800 dark:bg-amber-900 dark:text-amber-100",
    failed: "bg-red-100 text-red-800 dark:bg-red-900 dark:text-red-100",
    refunded: "bg-neutral-100 text-neutral-800 dark:bg-neutral-800 dark:text-neutral-100",
    partially_refunded: "bg-neutral-100 text-neutral-800 dark:bg-neutral-800 dark:text-neutral-100",
    expired: "bg-neutral-100 text-neutral-800 dark:bg-neutral-800 dark:text-neutral-100",
  };
  const cls = palette[status] ?? palette.expired;
  return <span className={`rounded-full px-2 py-0.5 text-xs ${cls}`}>{status}</span>;
}
