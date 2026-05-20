"use client";

import { useMemo, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import * as Dialog from "@radix-ui/react-dialog";

import {
  createExpense,
  listExpenses,
  type AdminExpenseView,
  type CreateExpenseRequest,
} from "@/lib/api/admin";
import { queryKeys } from "@/lib/query/keys";
import { useAdminAction } from "@/components/admin/admin-action-slot";
import { Button } from "@/components/ds/button";
import { Card } from "@/components/ds/card";
import { Chip } from "@/components/ds/chip";

const CATEGORIES: CreateExpenseRequest["category"][] = [
  "rent",
  "equipment",
  "salary",
  "marketing",
  "other",
];

function money(cents: number): string {
  return new Intl.NumberFormat("en-US", { style: "currency", currency: "USD" }).format(cents / 100);
}

export default function AdminExpensesPage() {
  const [open, setOpen] = useState(false);
  const queryClient = useQueryClient();
  const query = useQuery({ queryKey: queryKeys.admin.expenses(), queryFn: listExpenses });
  const expenses = query.data?.expenses ?? [];

  const topbarAction = useMemo(
    () => (
    <Button variant="primary" size="sm" onClick={() => setOpen(true)}>
      Add expense
    </Button>
    ),
    []
  );
  useAdminAction(topbarAction);

  return (
    <section data-testid="admin-expenses" className="space-y-5">
      {query.isError ? (
        <p role="alert" className="rounded-md bg-red-50 p-3 text-sm text-red-700">
          Could not load expenses.
        </p>
      ) : query.isLoading ? (
        <Skeleton />
      ) : expenses.length === 0 ? (
        <p data-testid="admin-expenses-empty" className="text-sm text-rally-subtle">
          No expenses recorded.
        </p>
      ) : (
        <Card p={20}>
          <ExpensesTable expenses={expenses} />
        </Card>
      )}
      <AddExpenseDialog
        open={open}
        onOpenChange={setOpen}
        onAdded={() => {
          setOpen(false);
          void queryClient.invalidateQueries({ queryKey: queryKeys.admin.expenses() });
        }}
      />
    </section>
  );
}

function ExpensesTable({ expenses }: { expenses: AdminExpenseView[] }) {
  return (
    <div className="overflow-x-auto">
      <table className="w-full min-w-[720px] text-sm">
        <thead>
          <tr className="border-b border-rally-line text-left">
            <th className="px-2 pb-3 font-mono text-[10px] font-bold uppercase tracking-overline text-rally-muted">
              Category
            </th>
            <th className="px-2 pb-3 text-right font-mono text-[10px] font-bold uppercase tracking-overline text-rally-muted">
              Amount
            </th>
            <th className="px-2 pb-3 font-mono text-[10px] font-bold uppercase tracking-overline text-rally-muted">
              Note
            </th>
            <th className="px-2 pb-3 font-mono text-[10px] font-bold uppercase tracking-overline text-rally-muted">
              Incurred
            </th>
          </tr>
        </thead>
        <tbody>
          {expenses.map((expense) => (
            <tr
              key={expense.expense_id}
              data-testid={`admin-expenses-row-${expense.expense_id}`}
              className="border-b border-rally-line last:border-0"
            >
              <td className="px-2 py-3">
                <Chip variant="manual" label={expense.category.toUpperCase()} />
              </td>
              <td className="px-2 py-3 text-right font-mono font-medium tabular-nums">
                {money(expense.amount_cents)}
              </td>
              <td className="px-2 py-3 text-rally-muted">{expense.note || "-"}</td>
              <td className="px-2 py-3 font-mono text-xs text-rally-muted">
                {new Date(expense.incurred_on).toLocaleDateString()}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

function AddExpenseDialog({
  open,
  onOpenChange,
  onAdded,
}: {
  open: boolean;
  onOpenChange: (value: boolean) => void;
  onAdded: () => void;
}) {
  const [category, setCategory] = useState<CreateExpenseRequest["category"]>("equipment");
  const [amount, setAmount] = useState("");
  const [note, setNote] = useState("");
  const [incurredOn, setIncurredOn] = useState(new Date().toISOString().slice(0, 10));
  const [error, setError] = useState<string | null>(null);
  const mutation = useMutation({
    mutationFn: (payload: CreateExpenseRequest) => createExpense(payload),
    onSuccess: () => {
      setAmount("");
      setNote("");
      setError(null);
      onAdded();
    },
    onError: (err: Error) => setError(err.message),
  });

  function submit(event: React.FormEvent) {
    event.preventDefault();
    const amountCents = Math.round(Number(amount) * 100);
    if (!amountCents || amountCents <= 0) {
      setError("Enter a valid amount.");
      return;
    }
    mutation.mutate({
      category,
      amount_cents: amountCents,
      note,
      incurred_on: incurredOn ? new Date(`${incurredOn}T00:00:00Z`).toISOString() : undefined,
    });
  }

  return (
    <Dialog.Root open={open} onOpenChange={onOpenChange}>
      <Dialog.Portal>
        <Dialog.Overlay className="fixed inset-0 z-50 bg-black/40" />
        <Dialog.Content className="fixed left-1/2 top-1/2 z-50 w-[min(92vw,420px)] -translate-x-1/2 -translate-y-1/2 rounded-lg bg-white p-6 shadow-xl">
          <Dialog.Title className="font-display text-lg font-semibold text-rally-ink">
            Add expense
          </Dialog.Title>
          {error && <p className="mt-3 rounded-md bg-red-50 p-2 text-sm text-red-700">{error}</p>}
          <form onSubmit={submit} className="mt-4 space-y-3">
            <label className="grid gap-1.5 text-sm font-medium text-rally-ink">
              Category
              <select
                value={category}
                onChange={(event) => setCategory(event.target.value as CreateExpenseRequest["category"])}
                className={inputClass}
              >
                {CATEGORIES.map((option) => (
                  <option key={option} value={option}>
                    {option}
                  </option>
                ))}
              </select>
            </label>
            <label className="grid gap-1.5 text-sm font-medium text-rally-ink">
              Amount
              <input
                type="number"
                min="0.01"
                step="0.01"
                value={amount}
                onChange={(event) => setAmount(event.target.value)}
                className={inputClass}
              />
            </label>
            <label className="grid gap-1.5 text-sm font-medium text-rally-ink">
              Date
              <input
                type="date"
                value={incurredOn}
                onChange={(event) => setIncurredOn(event.target.value)}
                className={inputClass}
              />
            </label>
            <label className="grid gap-1.5 text-sm font-medium text-rally-ink">
              Note
              <input value={note} onChange={(event) => setNote(event.target.value)} className={inputClass} />
            </label>
            <div className="flex justify-end gap-2 pt-2">
              <Dialog.Close asChild>
                <Button variant="secondary" size="sm">Cancel</Button>
              </Dialog.Close>
              <Button type="submit" variant="volt" size="sm" disabled={mutation.isPending}>
                {mutation.isPending ? "Saving..." : "Save"}
              </Button>
            </div>
          </form>
        </Dialog.Content>
      </Dialog.Portal>
    </Dialog.Root>
  );
}

const inputClass =
  "h-10 rounded-md border border-rally-line bg-white px-3 text-sm outline-none focus:border-blue-500";

function Skeleton() {
  return (
    <div className="space-y-2">
      {[0, 1, 2].map((i) => (
        <div key={i} className="h-14 animate-pulse rounded-lg bg-rally-paper" />
      ))}
    </div>
  );
}
