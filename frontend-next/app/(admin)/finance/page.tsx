"use client";

/**
 * Admin finance page.
 *
 * Shows: payouts table, expenses table (+ add expense dialog), and a
 * Recharts revenue bar chart (dynamically imported for code-splitting).
 */

import dynamic from "next/dynamic";
import { useState } from "react";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import * as Dialog from "@radix-ui/react-dialog";

import {
  listPayouts,
  listExpenses,
  getRevenue,
  createExpense,
  type CreateExpenseRequest,
} from "@/lib/api/admin";
import { queryKeys } from "@/lib/query/keys";

const RevenueChart = dynamic(() => import("@/components/admin/RevenueChart"), {
  ssr: false,
  loading: () => (
    <div className="h-48 animate-pulse rounded-lg bg-neutral-100 dark:bg-neutral-800" />
  ),
});

function formatCents(cents: number): string {
  return new Intl.NumberFormat("en-US", { style: "currency", currency: "USD" }).format(cents / 100);
}

export default function AdminFinancePage() {
  const [addExpenseOpen, setAddExpenseOpen] = useState(false);
  const queryClient = useQueryClient();

  const payoutsQuery = useQuery({
    queryKey: queryKeys.admin.payouts(),
    queryFn: () => listPayouts(),
  });

  const expensesQuery = useQuery({
    queryKey: queryKeys.admin.expenses(),
    queryFn: () => listExpenses(),
  });

  const revenueQuery = useQuery({
    queryKey: queryKeys.admin.revenue(),
    queryFn: () => getRevenue(),
  });

  const chartData = Object.entries(revenueQuery.data?.by_month ?? {})
    .sort(([a], [b]) => a.localeCompare(b))
    .slice(-12)
    .map(([month, cents]) => ({ month, revenue: cents / 100 }));

  return (
    <section data-testid="admin-finance">
      <h1 className="text-2xl font-semibold mb-6">Finance</h1>

      {/* Revenue chart */}
      <div className="mb-8 rounded-lg border border-neutral-200 dark:border-neutral-800 bg-white dark:bg-neutral-900 p-4">
        <h2 className="text-base font-semibold mb-3">Monthly revenue</h2>
        {revenueQuery.isLoading ? (
          <div className="h-48 animate-pulse rounded-lg bg-neutral-100 dark:bg-neutral-800" />
        ) : chartData.length > 0 ? (
          <RevenueChart data={chartData} />
        ) : (
          <p className="text-sm text-neutral-400">No revenue data yet.</p>
        )}
      </div>

      {/* Payouts */}
      <div className="mb-8">
        <h2 className="text-base font-semibold mb-3">Payouts</h2>
        {payoutsQuery.isLoading ? (
          <TableSkeleton />
        ) : (payoutsQuery.data?.payouts.length ?? 0) === 0 ? (
          <p className="text-sm text-neutral-500" data-testid="payouts-empty">
            No payouts yet.
          </p>
        ) : (
          <div className="overflow-x-auto rounded-lg border border-neutral-200 dark:border-neutral-800">
            <table className="w-full text-sm bg-white dark:bg-neutral-900">
              <thead>
                <tr className="border-b border-neutral-200 dark:border-neutral-700 text-left text-neutral-500">
                  <th className="px-4 py-3 font-medium">Payout ID</th>
                  <th className="px-4 py-3 font-medium">Amount</th>
                  <th className="px-4 py-3 font-medium">Status</th>
                  <th className="px-4 py-3 font-medium">Arrival</th>
                </tr>
              </thead>
              <tbody>
                {payoutsQuery.data!.payouts.map((p) => (
                  <tr
                    key={p.payout_id}
                    data-testid={`payout-row-${p.payout_id}`}
                    className="border-b border-neutral-100 dark:border-neutral-800 last:border-0"
                  >
                    <td className="px-4 py-3 font-mono text-xs text-neutral-500">
                      {p.payout_id.slice(0, 12)}…
                    </td>
                    <td className="px-4 py-3 tabular-nums font-medium">
                      {formatCents(p.amount_cents)}
                    </td>
                    <td className="px-4 py-3">
                      <span className="inline-block rounded-full bg-green-100 px-2 py-0.5 text-xs font-medium text-green-800 dark:bg-green-900 dark:text-green-200">
                        {p.status}
                      </span>
                    </td>
                    <td className="px-4 py-3 text-neutral-500">
                      {new Date(p.arrival_date).toLocaleDateString()}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </div>

      {/* Expenses */}
      <div>
        <div className="mb-3 flex items-center justify-between">
          <h2 className="text-base font-semibold">Expenses</h2>
          <button
            onClick={() => setAddExpenseOpen(true)}
            className="min-h-touch rounded-md bg-blue-600 px-3 text-sm font-medium text-white hover:bg-blue-700"
          >
            + Add expense
          </button>
        </div>
        {expensesQuery.isLoading ? (
          <TableSkeleton />
        ) : (expensesQuery.data?.expenses.length ?? 0) === 0 ? (
          <p className="text-sm text-neutral-500" data-testid="expenses-empty">
            No expenses recorded.
          </p>
        ) : (
          <div className="overflow-x-auto rounded-lg border border-neutral-200 dark:border-neutral-800">
            <table className="w-full text-sm bg-white dark:bg-neutral-900">
              <thead>
                <tr className="border-b border-neutral-200 dark:border-neutral-700 text-left text-neutral-500">
                  <th className="px-4 py-3 font-medium">Category</th>
                  <th className="px-4 py-3 font-medium">Amount</th>
                  <th className="px-4 py-3 font-medium">Note</th>
                  <th className="px-4 py-3 font-medium">Date</th>
                </tr>
              </thead>
              <tbody>
                {expensesQuery.data!.expenses.map((e) => (
                  <tr
                    key={e.expense_id}
                    data-testid={`expense-row-${e.expense_id}`}
                    className="border-b border-neutral-100 dark:border-neutral-800 last:border-0"
                  >
                    <td className="px-4 py-3 font-medium">{e.category}</td>
                    <td className="px-4 py-3 tabular-nums">{formatCents(e.amount_cents)}</td>
                    <td className="px-4 py-3 text-neutral-500">{e.note ?? "—"}</td>
                    <td className="px-4 py-3 text-neutral-500">
                      {new Date(e.incurred_on).toLocaleDateString()}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </div>

      <AddExpenseDialog
        open={addExpenseOpen}
        onOpenChange={setAddExpenseOpen}
        onAdded={() => {
          setAddExpenseOpen(false);
          void queryClient.invalidateQueries({ queryKey: queryKeys.admin.expenses() });
        }}
      />
    </section>
  );
}

// ---------------------------------------------------------------------------
// Add expense dialog
// ---------------------------------------------------------------------------

const EMPTY_EXPENSE: CreateExpenseRequest = {
  category: "",
  amount_cents: 0,
  note: "",
  incurred_on: new Date().toISOString().slice(0, 10),
};

function AddExpenseDialog({
  open,
  onOpenChange,
  onAdded,
}: {
  open: boolean;
  onOpenChange: (v: boolean) => void;
  onAdded: () => void;
}) {
  const [form, setForm] = useState<CreateExpenseRequest>(EMPTY_EXPENSE);
  const [amountDisplay, setAmountDisplay] = useState("");
  const [error, setError] = useState<string | null>(null);

  const mutation = useMutation({
    mutationFn: (payload: CreateExpenseRequest) => createExpense(payload),
    onSuccess: () => {
      setForm(EMPTY_EXPENSE);
      setAmountDisplay("");
      setError(null);
      onAdded();
    },
    onError: (err: Error) => {
      setError(err.message ?? "Failed to add expense.");
    },
  });

  const handleSubmit = (e: React.FormEvent) => {
    e.preventDefault();
    const amount_cents = Math.round(parseFloat(amountDisplay) * 100);
    if (!amount_cents || amount_cents <= 0) {
      setError("Enter a valid amount.");
      return;
    }
    mutation.mutate({ ...form, amount_cents });
  };

  return (
    <Dialog.Root open={open} onOpenChange={onOpenChange}>
      <Dialog.Portal>
        <Dialog.Overlay className="fixed inset-0 z-50 bg-black/40" />
        <Dialog.Content
          className="fixed left-1/2 top-1/2 z-50 w-full max-w-sm -translate-x-1/2 -translate-y-1/2 rounded-xl bg-white dark:bg-neutral-900 p-6 shadow-xl focus:outline-none"
          aria-describedby="add-expense-desc"
        >
          <Dialog.Title className="text-lg font-semibold mb-1">Add expense</Dialog.Title>
          <Dialog.Description id="add-expense-desc" className="text-sm text-neutral-500 mb-4">
            Record an operating expense.
          </Dialog.Description>

          {error && (
            <p role="alert" className="mb-3 rounded-md bg-red-50 p-2 text-sm text-red-700 dark:bg-red-950 dark:text-red-300">
              {error}
            </p>
          )}

          <form onSubmit={handleSubmit} className="space-y-3">
            <Field label="Category" required>
              <input
                type="text"
                required
                value={form.category}
                onChange={(e) => setForm((f) => ({ ...f, category: e.target.value }))}
                className={inputClass}
                placeholder="Equipment, venue, marketing…"
              />
            </Field>
            <Field label="Amount (USD)" required>
              <input
                type="number"
                required
                min="0.01"
                step="0.01"
                value={amountDisplay}
                onChange={(e) => setAmountDisplay(e.target.value)}
                className={inputClass}
                placeholder="0.00"
              />
            </Field>
            <Field label="Note">
              <input
                type="text"
                value={form.note ?? ""}
                onChange={(e) => setForm((f) => ({ ...f, note: e.target.value }))}
                className={inputClass}
              />
            </Field>
            <Field label="Date" required>
              <input
                type="date"
                required
                value={form.incurred_on}
                onChange={(e) => setForm((f) => ({ ...f, incurred_on: e.target.value }))}
                className={inputClass}
              />
            </Field>
            <div className="flex justify-end gap-2 pt-2">
              <Dialog.Close asChild>
                <button
                  type="button"
                  className="min-h-touch rounded-md border border-neutral-300 px-4 text-sm dark:border-neutral-700"
                >
                  Cancel
                </button>
              </Dialog.Close>
              <button
                type="submit"
                disabled={mutation.isPending}
                className="min-h-touch rounded-md bg-blue-600 px-4 text-sm font-medium text-white hover:bg-blue-700 disabled:opacity-60"
              >
                {mutation.isPending ? "Saving…" : "Save"}
              </button>
            </div>
          </form>
        </Dialog.Content>
      </Dialog.Portal>
    </Dialog.Root>
  );
}

const inputClass =
  "w-full rounded-md border border-neutral-300 dark:border-neutral-700 bg-white dark:bg-neutral-900 px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500";

function Field({
  label,
  required,
  children,
}: {
  label: string;
  required?: boolean;
  children: React.ReactNode;
}) {
  return (
    <label className="block">
      <span className="mb-1 block text-sm font-medium text-neutral-700 dark:text-neutral-300">
        {label}
        {required && <span aria-hidden="true" className="ml-0.5 text-red-500">*</span>}
      </span>
      {children}
    </label>
  );
}

function TableSkeleton() {
  return (
    <div className="space-y-2">
      {[0, 1, 2].map((i) => (
        <div key={i} className="h-12 animate-pulse rounded-lg bg-neutral-100 dark:bg-neutral-800" />
      ))}
    </div>
  );
}
