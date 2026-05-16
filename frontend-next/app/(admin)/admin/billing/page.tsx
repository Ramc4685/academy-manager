"use client";

import { useState } from "react";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import * as Dialog from "@radix-ui/react-dialog";

import {
  listAdminPayments,
  refundPayment,
  type AdminPaymentView,
  type RefundRequest,
} from "@/lib/api/admin";
import { queryKeys } from "@/lib/query/keys";

function formatCents(cents: number): string {
  return new Intl.NumberFormat("en-US", { style: "currency", currency: "USD" }).format(cents / 100);
}

export default function AdminBillingPage() {
  const [refundTarget, setRefundTarget] = useState<AdminPaymentView | null>(null);
  const queryClient = useQueryClient();

  const { data, isLoading, isError, refetch } = useQuery({
    queryKey: queryKeys.admin.payments(),
    queryFn: () => listAdminPayments(),
  });

  const payments = data?.payments ?? [];

  return (
    <section data-testid="admin-billing">
      <h1 className="text-2xl font-semibold mb-6">Billing</h1>

      {isError && (
        <div
          role="alert"
          className="mb-4 rounded-md border border-red-200 bg-red-50 p-4 text-sm text-red-800 dark:border-red-900 dark:bg-red-950 dark:text-red-200"
        >
          <p>Failed to load payments.</p>
          <button
            onClick={() => void refetch()}
            className="mt-2 min-h-touch rounded-md border px-3"
          >
            Retry
          </button>
        </div>
      )}

      {isLoading ? (
        <TableSkeleton />
      ) : payments.length === 0 ? (
        <p className="text-neutral-500 text-sm" data-testid="billing-empty">
          No payments found.
        </p>
      ) : (
        <div className="overflow-x-auto rounded-lg border border-neutral-200 dark:border-neutral-800">
          <table className="w-full text-sm bg-white dark:bg-neutral-900">
            <thead>
              <tr className="border-b border-neutral-200 dark:border-neutral-700 text-left text-neutral-500">
                <th className="px-4 py-3 font-medium">Payment ID</th>
                <th className="px-4 py-3 font-medium">Amount</th>
                <th className="px-4 py-3 font-medium">Refunded</th>
                <th className="px-4 py-3 font-medium">Status</th>
                <th className="px-4 py-3 font-medium">Date</th>
                <th className="px-4 py-3 font-medium sr-only">Actions</th>
              </tr>
            </thead>
            <tbody>
              {payments.map((p) => (
                <tr
                  key={p.payment_id}
                  data-testid={`payment-row-${p.payment_id}`}
                  className="border-b border-neutral-100 dark:border-neutral-800 last:border-0"
                >
                  <td className="px-4 py-3 font-mono text-xs text-neutral-500">
                    {p.payment_id.slice(0, 12)}…
                  </td>
                  <td className="px-4 py-3 tabular-nums font-medium">
                    {formatCents(p.amount_cents)}
                  </td>
                  <td className="px-4 py-3 tabular-nums text-neutral-500">
                    {p.refunded_cents > 0 ? formatCents(p.refunded_cents) : "—"}
                  </td>
                  <td className="px-4 py-3">
                    <PaymentStatusBadge status={p.status} />
                  </td>
                  <td className="px-4 py-3 text-neutral-500">
                    {new Date(p.created_at).toLocaleDateString()}
                  </td>
                  <td className="px-4 py-3 text-right">
                    <button
                      onClick={() => setRefundTarget(p)}
                      disabled={p.status === "refunded" || p.status === "failed"}
                      className="min-h-touch rounded-md border border-amber-300 px-2 text-xs text-amber-700 hover:bg-amber-50 dark:border-amber-700 dark:text-amber-400 disabled:cursor-not-allowed disabled:opacity-40"
                      aria-label={`Refund payment ${p.payment_id}`}
                    >
                      Refund
                    </button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      <RefundDialog
        payment={refundTarget}
        onClose={() => setRefundTarget(null)}
        onRefunded={() => {
          setRefundTarget(null);
          void queryClient.invalidateQueries({ queryKey: queryKeys.admin.payments() });
        }}
      />
    </section>
  );
}

// ---------------------------------------------------------------------------
// Status badge
// ---------------------------------------------------------------------------

function PaymentStatusBadge({ status }: { status: string }) {
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
      {status.replace("_", " ")}
    </span>
  );
}

// ---------------------------------------------------------------------------
// Refund dialog
// ---------------------------------------------------------------------------

function RefundDialog({
  payment,
  onClose,
  onRefunded,
}: {
  payment: AdminPaymentView | null;
  onClose: () => void;
  onRefunded: () => void;
}) {
  const [amountInput, setAmountInput] = useState("");
  const [reason, setReason] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [result, setResult] = useState<{ refunded_cents: number } | null>(null);

  const mutation = useMutation({
    mutationFn: (payload: RefundRequest) => refundPayment(payload),
    onSuccess: (res) => {
      setResult({ refunded_cents: res.refunded_cents });
      setError(null);
    },
    onError: (err: Error) => {
      setError(err.message ?? "Refund failed.");
    },
  });

  const handleClose = () => {
    setAmountInput("");
    setReason("");
    setError(null);
    setResult(null);
    onClose();
  };

  const handleSubmit = (e: React.FormEvent) => {
    e.preventDefault();
    if (!payment) return;
    const amountCents = amountInput
      ? Math.round(parseFloat(amountInput) * 100)
      : undefined;
    mutation.mutate({
      payment_id: payment.payment_id,
      amount_cents: amountCents,
      reason,
    });
  };

  const open = payment !== null;

  return (
    <Dialog.Root open={open} onOpenChange={(v) => !v && handleClose()}>
      <Dialog.Portal>
        <Dialog.Overlay className="fixed inset-0 z-50 bg-black/40" />
        <Dialog.Content
          className="fixed left-1/2 top-1/2 z-50 w-full max-w-sm -translate-x-1/2 -translate-y-1/2 rounded-xl bg-white dark:bg-neutral-900 p-6 shadow-xl focus:outline-none"
          aria-describedby="refund-dialog-desc"
        >
          <Dialog.Title className="text-lg font-semibold mb-1">Issue refund</Dialog.Title>
          <Dialog.Description id="refund-dialog-desc" className="text-sm text-neutral-500 mb-4">
            {payment && (
              <>
                Payment <span className="font-mono">{payment.payment_id.slice(0, 12)}…</span> for{" "}
                <strong>{formatCents(payment.amount_cents)}</strong>. Leave amount blank for full
                refund.
              </>
            )}
          </Dialog.Description>

          {result ? (
            <div className="space-y-4">
              <p className="rounded-md bg-green-50 p-3 text-sm text-green-800 dark:bg-green-950 dark:text-green-200">
                Refunded {formatCents(result.refunded_cents)} successfully.
              </p>
              <div className="flex justify-end">
                <button
                  onClick={() => {
                    onRefunded();
                    handleClose();
                  }}
                  className="min-h-touch rounded-md bg-blue-600 px-4 text-sm font-medium text-white hover:bg-blue-700"
                >
                  Done
                </button>
              </div>
            </div>
          ) : (
            <form onSubmit={handleSubmit} className="space-y-3">
              {error && (
                <p role="alert" className="rounded-md bg-red-50 p-2 text-sm text-red-700 dark:bg-red-950 dark:text-red-300">
                  {error}
                </p>
              )}
              <label className="block">
                <span className="mb-1 block text-sm font-medium text-neutral-700 dark:text-neutral-300">
                  Amount (USD) — leave blank for full refund
                </span>
                <input
                  type="number"
                  min="0.01"
                  step="0.01"
                  value={amountInput}
                  onChange={(e) => setAmountInput(e.target.value)}
                  placeholder={
                    payment ? `${(payment.amount_cents / 100).toFixed(2)}` : ""
                  }
                  className={inputClass}
                />
              </label>
              <label className="block">
                <span className="mb-1 block text-sm font-medium text-neutral-700 dark:text-neutral-300">
                  Reason <span aria-hidden="true" className="ml-0.5 text-red-500">*</span>
                </span>
                <input
                  type="text"
                  required
                  value={reason}
                  onChange={(e) => setReason(e.target.value)}
                  className={inputClass}
                  placeholder="Duplicate charge, customer request…"
                />
              </label>
              <div className="flex justify-end gap-2 pt-2">
                <button
                  type="button"
                  onClick={handleClose}
                  className="min-h-touch rounded-md border border-neutral-300 px-4 text-sm dark:border-neutral-700"
                >
                  Cancel
                </button>
                <button
                  type="submit"
                  disabled={mutation.isPending}
                  className="min-h-touch rounded-md bg-amber-600 px-4 text-sm font-medium text-white hover:bg-amber-700 disabled:opacity-60"
                >
                  {mutation.isPending ? "Processing…" : "Refund"}
                </button>
              </div>
            </form>
          )}
        </Dialog.Content>
      </Dialog.Portal>
    </Dialog.Root>
  );
}

const inputClass =
  "w-full rounded-md border border-neutral-300 dark:border-neutral-700 bg-white dark:bg-neutral-900 px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500";

function TableSkeleton() {
  return (
    <div className="space-y-2">
      {[0, 1, 2, 3].map((i) => (
        <div key={i} className="h-12 animate-pulse rounded-lg bg-neutral-100 dark:bg-neutral-800" />
      ))}
    </div>
  );
}
