"use client";

import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import * as Dialog from "@radix-ui/react-dialog";

import {
  applyPaymentDiscount,
  generateMonthlyPayments,
  listAdminPayments,
  markPaymentPaid,
  refundPayment,
  undoPaymentPaid,
  type AdminPaymentView,
  type RefundRequest,
} from "@/lib/api/admin";
import { queryKeys } from "@/lib/query/keys";

function formatCents(cents: number): string {
  return new Intl.NumberFormat("en-US", { style: "currency", currency: "USD" }).format(cents / 100);
}

function finalCents(payment: AdminPaymentView): number {
  return payment.final_amount_cents ?? Math.max(payment.amount_cents - payment.discount_cents, 0);
}

export default function AdminBillingPage() {
  const [refundTarget, setRefundTarget] = useState<AdminPaymentView | null>(null);
  const [paidTarget, setPaidTarget] = useState<AdminPaymentView | null>(null);
  const [discountTarget, setDiscountTarget] = useState<AdminPaymentView | null>(null);
  const [generateOpen, setGenerateOpen] = useState(false);
  const queryClient = useQueryClient();

  const { data, isLoading, isError, refetch } = useQuery({
    queryKey: queryKeys.admin.payments(),
    queryFn: () => listAdminPayments(),
  });

  const undoMutation = useMutation({
    mutationFn: (paymentId: string) => undoPaymentPaid(paymentId),
    onSuccess: () => void queryClient.invalidateQueries({ queryKey: queryKeys.admin.payments() }),
  });

  const payments = data?.payments ?? [];
  const pendingCount = payments.filter((p) => p.status === "pending").length;
  const paidCents = payments
    .filter((p) => ["succeeded", "partially_refunded", "refunded"].includes(p.status))
    .reduce((sum, p) => sum + finalCents(p) - p.refunded_cents, 0);

  return (
    <section data-testid="admin-billing" className="space-y-5">
      <div className="flex flex-col gap-3 sm:flex-row sm:items-end sm:justify-between">
        <div>
          <h1 className="text-2xl font-semibold">Billing</h1>
          <p className="mt-1 text-sm text-neutral-500">
            Manual invoices, payment status, discounts, and refunds.
          </p>
        </div>
        <button
          type="button"
          onClick={() => setGenerateOpen(true)}
          className="min-h-touch rounded-md bg-blue-600 px-4 text-sm font-medium text-white hover:bg-blue-700"
        >
          Generate monthly
        </button>
      </div>

      <div className="grid gap-3 sm:grid-cols-3">
        <Metric label="Open invoices" value={String(pendingCount)} />
        <Metric label="Collected" value={formatCents(paidCents)} />
        <Metric label="Payments" value={String(payments.length)} />
      </div>

      {isError && (
        <div
          role="alert"
          className="rounded-md border border-red-200 bg-red-50 p-4 text-sm text-red-800 dark:border-red-900 dark:bg-red-950 dark:text-red-200"
        >
          <p>Failed to load payments.</p>
          <button onClick={() => void refetch()} className="mt-2 min-h-touch rounded-md border px-3">
            Retry
          </button>
        </div>
      )}

      {isLoading ? (
        <TableSkeleton />
      ) : payments.length === 0 ? (
        <p className="text-sm text-neutral-500" data-testid="billing-empty">
          No payments found.
        </p>
      ) : (
        <div className="overflow-x-auto rounded-lg border border-neutral-200 dark:border-neutral-800">
          <table className="w-full min-w-[980px] bg-white text-sm dark:bg-neutral-900">
            <thead>
              <tr className="border-b border-neutral-200 text-left text-neutral-500 dark:border-neutral-700">
                <th className="px-4 py-3 font-medium">Invoice</th>
                <th className="px-4 py-3 font-medium">Student</th>
                <th className="px-4 py-3 font-medium">Period</th>
                <th className="px-4 py-3 font-medium">Amount</th>
                <th className="px-4 py-3 font-medium">Discount</th>
                <th className="px-4 py-3 font-medium">Final</th>
                <th className="px-4 py-3 font-medium">Status</th>
                <th className="px-4 py-3 font-medium">Method</th>
                <th className="px-4 py-3 font-medium sr-only">Actions</th>
              </tr>
            </thead>
            <tbody>
              {payments.map((payment) => (
                <tr
                  key={payment.payment_id}
                  data-testid={`payment-row-${payment.payment_id}`}
                  className="border-b border-neutral-100 last:border-0 dark:border-neutral-800"
                >
                  <td className="px-4 py-3">
                    <div className="font-mono text-xs text-neutral-600 dark:text-neutral-300">
                      {payment.invoice_number || `${payment.payment_id.slice(0, 12)}...`}
                    </div>
                    <div className="mt-1 text-xs text-neutral-400">
                      {new Date(payment.created_at).toLocaleDateString()}
                    </div>
                  </td>
                  <td className="px-4 py-3">
                    <div className="font-medium text-neutral-900 dark:text-neutral-50">
                      {payment.student_name || "Unassigned"}
                    </div>
                    <div className="mt-1 font-mono text-xs text-neutral-400">
                      {payment.parent_id.slice(0, 14)}
                    </div>
                  </td>
                  <td className="px-4 py-3 text-neutral-600 dark:text-neutral-300">
                    {payment.period || "-"}
                  </td>
                  <td className="px-4 py-3 tabular-nums">{formatCents(payment.amount_cents)}</td>
                  <td className="px-4 py-3 tabular-nums text-neutral-500">
                    {payment.discount_cents ? formatCents(payment.discount_cents) : "-"}
                  </td>
                  <td className="px-4 py-3 tabular-nums font-medium">
                    {formatCents(finalCents(payment))}
                  </td>
                  <td className="px-4 py-3">
                    <PaymentStatusBadge status={payment.status} />
                  </td>
                  <td className="px-4 py-3 text-neutral-500">
                    {payment.payment_method || (payment.stripe_linked ? "Stripe" : "-")}
                  </td>
                  <td className="px-4 py-3">
                    <PaymentActions
                      payment={payment}
                      onDiscount={() => setDiscountTarget(payment)}
                      onPaid={() => setPaidTarget(payment)}
                      onRefund={() => setRefundTarget(payment)}
                      onUndo={() => undoMutation.mutate(payment.payment_id)}
                      undoPending={undoMutation.isPending}
                    />
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      <GenerateDialog
        open={generateOpen}
        onOpenChange={setGenerateOpen}
        onGenerated={() => void queryClient.invalidateQueries({ queryKey: queryKeys.admin.payments() })}
      />
      <DiscountDialog
        payment={discountTarget}
        onClose={() => setDiscountTarget(null)}
        onSaved={() => {
          setDiscountTarget(null);
          void queryClient.invalidateQueries({ queryKey: queryKeys.admin.payments() });
        }}
      />
      <MarkPaidDialog
        payment={paidTarget}
        onClose={() => setPaidTarget(null)}
        onSaved={() => {
          setPaidTarget(null);
          void queryClient.invalidateQueries({ queryKey: queryKeys.admin.payments() });
        }}
      />
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

function Metric({ label, value }: { label: string; value: string }) {
  return (
    <div className="rounded-lg border border-neutral-200 bg-white p-4 dark:border-neutral-800 dark:bg-neutral-900">
      <p className="text-xs font-medium uppercase tracking-wide text-neutral-500">{label}</p>
      <p className="mt-2 text-xl font-semibold tabular-nums">{value}</p>
    </div>
  );
}

function PaymentActions({
  payment,
  onDiscount,
  onPaid,
  onRefund,
  onUndo,
  undoPending,
}: {
  payment: AdminPaymentView;
  onDiscount: () => void;
  onPaid: () => void;
  onRefund: () => void;
  onUndo: () => void;
  undoPending: boolean;
}) {
  const isPending = payment.status === "pending";
  const isPaid = payment.status === "succeeded" || payment.status === "partially_refunded";
  return (
    <div className="flex justify-end gap-2">
      {isPending && (
        <>
          <button type="button" onClick={onDiscount} className={secondaryButtonClass}>
            Discount
          </button>
          <button type="button" onClick={onPaid} className={primaryButtonClass}>
            Mark paid
          </button>
        </>
      )}
      {isPaid && (
        <>
          <button type="button" onClick={onRefund} className={warningButtonClass}>
            Refund
          </button>
          <button
            type="button"
            onClick={onUndo}
            disabled={payment.stripe_linked || undoPending}
            className={secondaryButtonClass}
            title={payment.stripe_linked ? "Stripe payments must be refunded" : "Undo manual paid"}
          >
            Undo
          </button>
        </>
      )}
    </div>
  );
}

function PaymentStatusBadge({ status }: { status: string }) {
  const colors: Record<string, string> = {
    succeeded: "bg-green-100 text-green-800 dark:bg-green-900 dark:text-green-200",
    pending: "bg-amber-100 text-amber-800 dark:bg-amber-900 dark:text-amber-200",
    refunded: "bg-neutral-100 text-neutral-600 dark:bg-neutral-800 dark:text-neutral-300",
    partially_refunded: "bg-blue-100 text-blue-800 dark:bg-blue-900 dark:text-blue-200",
    failed: "bg-red-100 text-red-800 dark:bg-red-900 dark:text-red-200",
    expired: "bg-neutral-100 text-neutral-600 dark:bg-neutral-800 dark:text-neutral-300",
  };
  const label = status === "succeeded" ? "paid" : status.replace("_", " ");
  return (
    <span
      className={`inline-block rounded-full px-2 py-0.5 text-xs font-medium ${
        colors[status] ?? "bg-neutral-100 text-neutral-600"
      }`}
    >
      {label}
    </span>
  );
}

function GenerateDialog({
  open,
  onOpenChange,
  onGenerated,
}: {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  onGenerated: () => void;
}) {
  const [period, setPeriod] = useState("");
  const [result, setResult] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const mutation = useMutation({
    mutationFn: () => generateMonthlyPayments({ period }),
    onSuccess: (res) => {
      setResult(`${res.created} created, ${res.skipped_existing} already existed.`);
      setError(null);
      onGenerated();
    },
    onError: (err: Error) => setError(err.message ?? "Generation failed."),
  });

  const close = () => {
    setResult(null);
    setError(null);
    onOpenChange(false);
  };

  return (
    <Dialog.Root
      open={open}
      onOpenChange={(nextOpen) => {
        if (nextOpen && !period) setPeriod(new Date().toISOString().slice(0, 7));
        if (!nextOpen) close();
        else onOpenChange(true);
      }}
    >
      <Dialog.Portal>
        <Dialog.Overlay className="fixed inset-0 z-50 bg-black/40" />
        <Dialog.Content className={dialogClass}>
          <Dialog.Title className="text-lg font-semibold">Generate monthly invoices</Dialog.Title>
          <Dialog.Description className="mt-1 text-sm text-neutral-500">
            Creates pending invoices for active manual enrollments.
          </Dialog.Description>
          <form
            className="mt-4 space-y-3"
            onSubmit={(event) => {
              event.preventDefault();
              mutation.mutate();
            }}
          >
            {error && <Alert tone="red">{error}</Alert>}
            {result && <Alert tone="green">{result}</Alert>}
            <label className="block">
              <span className={labelClass}>Period</span>
              <input
                type="month"
                required
                value={period}
                onChange={(event) => setPeriod(event.target.value)}
                className={inputClass}
              />
            </label>
            <DialogActions onCancel={close} submitLabel={mutation.isPending ? "Generating..." : "Generate"} />
          </form>
        </Dialog.Content>
      </Dialog.Portal>
    </Dialog.Root>
  );
}

function DiscountDialog({
  payment,
  onClose,
  onSaved,
}: {
  payment: AdminPaymentView | null;
  onClose: () => void;
  onSaved: () => void;
}) {
  const [amountInput, setAmountInput] = useState("");
  const [error, setError] = useState<string | null>(null);
  const mutation = useMutation({
    mutationFn: () =>
      applyPaymentDiscount(payment!.payment_id, {
        discount_cents: Math.round(Number(amountInput) * 100),
      }),
    onSuccess: () => {
      setAmountInput("");
      setError(null);
      onSaved();
    },
    onError: (err: Error) => setError(err.message ?? "Discount failed."),
  });

  return (
    <Dialog.Root open={payment !== null} onOpenChange={(open) => !open && onClose()}>
      <Dialog.Portal>
        <Dialog.Overlay className="fixed inset-0 z-50 bg-black/40" />
        <Dialog.Content className={dialogClass}>
          <Dialog.Title className="text-lg font-semibold">Apply discount</Dialog.Title>
          <Dialog.Description className="mt-1 text-sm text-neutral-500">
            {payment ? `Invoice ${payment.invoice_number || payment.payment_id.slice(0, 12)}` : ""}
          </Dialog.Description>
          <form
            className="mt-4 space-y-3"
            onSubmit={(event) => {
              event.preventDefault();
              mutation.mutate();
            }}
          >
            {error && <Alert tone="red">{error}</Alert>}
            <label className="block">
              <span className={labelClass}>Discount (USD)</span>
              <input
                type="number"
                min="0"
                step="0.01"
                required
                value={amountInput}
                onChange={(event) => setAmountInput(event.target.value)}
                className={inputClass}
              />
            </label>
            <DialogActions onCancel={onClose} submitLabel={mutation.isPending ? "Saving..." : "Save"} />
          </form>
        </Dialog.Content>
      </Dialog.Portal>
    </Dialog.Root>
  );
}

function MarkPaidDialog({
  payment,
  onClose,
  onSaved,
}: {
  payment: AdminPaymentView | null;
  onClose: () => void;
  onSaved: () => void;
}) {
  const [method, setMethod] = useState("cash");
  const [notes, setNotes] = useState("");
  const [error, setError] = useState<string | null>(null);
  const mutation = useMutation({
    mutationFn: () => markPaymentPaid(payment!.payment_id, { payment_method: method, notes }),
    onSuccess: () => {
      setNotes("");
      setError(null);
      onSaved();
    },
    onError: (err: Error) => setError(err.message ?? "Mark paid failed."),
  });

  return (
    <Dialog.Root open={payment !== null} onOpenChange={(open) => !open && onClose()}>
      <Dialog.Portal>
        <Dialog.Overlay className="fixed inset-0 z-50 bg-black/40" />
        <Dialog.Content className={dialogClass}>
          <Dialog.Title className="text-lg font-semibold">Mark invoice paid</Dialog.Title>
          <Dialog.Description className="mt-1 text-sm text-neutral-500">
            {payment ? `${formatCents(finalCents(payment))} for ${payment.student_name || "student"}` : ""}
          </Dialog.Description>
          <form
            className="mt-4 space-y-3"
            onSubmit={(event) => {
              event.preventDefault();
              mutation.mutate();
            }}
          >
            {error && <Alert tone="red">{error}</Alert>}
            <label className="block">
              <span className={labelClass}>Payment method</span>
              <select value={method} onChange={(event) => setMethod(event.target.value)} className={inputClass}>
                <option value="cash">Cash</option>
                <option value="check">Check</option>
                <option value="zelle">Zelle</option>
                <option value="venmo">Venmo</option>
                <option value="other">Other</option>
              </select>
            </label>
            <label className="block">
              <span className={labelClass}>Notes</span>
              <input value={notes} onChange={(event) => setNotes(event.target.value)} className={inputClass} />
            </label>
            <DialogActions onCancel={onClose} submitLabel={mutation.isPending ? "Saving..." : "Mark paid"} />
          </form>
        </Dialog.Content>
      </Dialog.Portal>
    </Dialog.Root>
  );
}

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
    onError: (err: Error) => setError(err.message ?? "Refund failed."),
  });

  const close = () => {
    setAmountInput("");
    setReason("");
    setError(null);
    setResult(null);
    onClose();
  };

  return (
    <Dialog.Root open={payment !== null} onOpenChange={(open) => !open && close()}>
      <Dialog.Portal>
        <Dialog.Overlay className="fixed inset-0 z-50 bg-black/40" />
        <Dialog.Content className={dialogClass}>
          <Dialog.Title className="text-lg font-semibold">Issue refund</Dialog.Title>
          <Dialog.Description className="mt-1 text-sm text-neutral-500">
            {payment ? `Refund ${formatCents(finalCents(payment))} invoice.` : ""}
          </Dialog.Description>
          {result ? (
            <div className="mt-4 space-y-4">
              <Alert tone="green">Refunded {formatCents(result.refunded_cents)}.</Alert>
              <div className="flex justify-end">
                <button
                  type="button"
                  onClick={() => {
                    onRefunded();
                    close();
                  }}
                  className={primaryButtonClass}
                >
                  Done
                </button>
              </div>
            </div>
          ) : (
            <form
              className="mt-4 space-y-3"
              onSubmit={(event) => {
                event.preventDefault();
                if (!payment) return;
                mutation.mutate({
                  payment_id: payment.payment_id,
                  amount_cents: amountInput ? Math.round(Number(amountInput) * 100) : undefined,
                  reason,
                });
              }}
            >
              {error && <Alert tone="red">{error}</Alert>}
              <label className="block">
                <span className={labelClass}>Amount (USD)</span>
                <input
                  type="number"
                  min="0.01"
                  step="0.01"
                  value={amountInput}
                  onChange={(event) => setAmountInput(event.target.value)}
                  placeholder={payment ? (finalCents(payment) / 100).toFixed(2) : ""}
                  className={inputClass}
                />
              </label>
              <label className="block">
                <span className={labelClass}>Reason</span>
                <input
                  type="text"
                  required
                  value={reason}
                  onChange={(event) => setReason(event.target.value)}
                  className={inputClass}
                />
              </label>
              <DialogActions onCancel={close} submitLabel={mutation.isPending ? "Processing..." : "Refund"} />
            </form>
          )}
        </Dialog.Content>
      </Dialog.Portal>
    </Dialog.Root>
  );
}

function DialogActions({ onCancel, submitLabel }: { onCancel: () => void; submitLabel: string }) {
  return (
    <div className="flex justify-end gap-2 pt-2">
      <button type="button" onClick={onCancel} className={secondaryButtonClass}>
        Cancel
      </button>
      <button type="submit" className={primaryButtonClass}>
        {submitLabel}
      </button>
    </div>
  );
}

function Alert({ tone, children }: { tone: "green" | "red"; children: React.ReactNode }) {
  const cls =
    tone === "green"
      ? "bg-green-50 text-green-800 dark:bg-green-950 dark:text-green-200"
      : "bg-red-50 text-red-700 dark:bg-red-950 dark:text-red-300";
  return <p className={`rounded-md p-3 text-sm ${cls}`}>{children}</p>;
}

const dialogClass =
  "fixed left-1/2 top-1/2 z-50 w-full max-w-md -translate-x-1/2 -translate-y-1/2 rounded-lg bg-white p-6 shadow-xl focus:outline-none dark:bg-neutral-900";
const inputClass =
  "w-full rounded-md border border-neutral-300 bg-white px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500 dark:border-neutral-700 dark:bg-neutral-900";
const labelClass = "mb-1 block text-sm font-medium text-neutral-700 dark:text-neutral-300";
const primaryButtonClass =
  "min-h-touch rounded-md bg-blue-600 px-3 text-sm font-medium text-white hover:bg-blue-700 disabled:cursor-not-allowed disabled:opacity-50";
const secondaryButtonClass =
  "min-h-touch rounded-md border border-neutral-300 px-3 text-sm hover:bg-neutral-50 disabled:cursor-not-allowed disabled:opacity-40 dark:border-neutral-700 dark:hover:bg-neutral-800";
const warningButtonClass =
  "min-h-touch rounded-md border border-amber-300 px-3 text-sm text-amber-700 hover:bg-amber-50 dark:border-amber-700 dark:text-amber-400";

function TableSkeleton() {
  return (
    <div className="space-y-2">
      {[0, 1, 2, 3].map((i) => (
        <div key={i} className="h-12 animate-pulse rounded-lg bg-neutral-100 dark:bg-neutral-800" />
      ))}
    </div>
  );
}
