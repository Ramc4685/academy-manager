"use client";

/**
 * Admin payments — Rally restyle.
 *
 * Rally MONEY route for payments. Preserves: generate-monthly,
 * apply-discount, mark-paid, undo-paid, refund. Refund disabled when
 * payment isn't eligible.
 */

import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import * as Dialog from "@radix-ui/react-dialog";

import {
  applyPaymentDiscount,
  generateAdminInvoiceArtifact,
  generateMonthlyPayments,
  getAdminInvoiceDetail,
  listAdminPayments,
  markPaymentPaid,
  refundPayment,
  undoPaymentPaid,
  type AdminPaymentStatus,
  type AdminPaymentView,
  type RefundRequest,
} from "@/lib/api/admin";
import { queryKeys } from "@/lib/query/keys";

import { Button } from "@/components/ds/button";
import { Card } from "@/components/ds/card";
import { Chip, type ChipVariant } from "@/components/ds/chip";
import { BigNum, Overline } from "@/components/ds/typography";

function formatCents(cents: number): string {
  return new Intl.NumberFormat("en-US", { style: "currency", currency: "USD" }).format(cents / 100);
}

function finalCents(payment: AdminPaymentView): number {
  return payment.final_amount_cents ?? Math.max(payment.amount_cents - payment.discount_cents, 0);
}

function paymentDisplayLabel(payment: AdminPaymentView): string {
  if (payment.period) return `Tuition for ${payment.period}`;
  return payment.stripe_linked ? "Stripe payment" : "Manual payment";
}

function paidCents(payment: AdminPaymentView): number | null {
  if (payment.paid_amount_cents > 0) return Math.max(payment.paid_amount_cents - payment.refunded_cents, 0);
  if (!["succeeded", "paid", "partially_refunded", "refunded"].includes(payment.status)) return null;
  return Math.max(finalCents(payment) - payment.refunded_cents, 0);
}

function adminPaymentStatus(payment: AdminPaymentView): string {
  return payment.status as AdminPaymentStatus;
}

type PaymentStatusChip = { variant: ChipVariant; label: string };

const STATUS_CHIP: Record<AdminPaymentStatus, PaymentStatusChip> = {
  succeeded: { variant: "paid", label: "PAID" },
  paid: { variant: "paid", label: "PAID" },
  pending: { variant: "pending", label: "PENDING" },
  partially_paid: { variant: "partial", label: "PARTIAL" },
  refunded: { variant: "refunded", label: "REFUNDED" },
  partially_refunded: { variant: "partial", label: "PARTIAL" },
  failed: { variant: "failed", label: "FAILED" },
  expired: { variant: "expired", label: "EXPIRED" },
  waived: { variant: "waived", label: "WAIVED" },
};

function statusChip(status: string | null | undefined): PaymentStatusChip {
  if (status && status in STATUS_CHIP) {
    return STATUS_CHIP[status as AdminPaymentStatus];
  }
  return {
    variant: "pending",
    label: (status || "unknown").replaceAll("_", " ").toUpperCase(),
  };
}

function methodChip(payment: AdminPaymentView): { variant: ChipVariant; label: string } | null {
  if (payment.stripe_linked) return { variant: "autopayOn", label: "STRIPE" };
  if (payment.payment_method) {
    return { variant: "manual", label: payment.payment_method.toUpperCase() };
  }
  return null;
}

export default function AdminPaymentsPage() {
  const [refundTarget, setRefundTarget] = useState<AdminPaymentView | null>(null);
  const [paidTarget, setPaidTarget] = useState<AdminPaymentView | null>(null);
  const [discountTarget, setDiscountTarget] = useState<AdminPaymentView | null>(null);
  const [invoiceTarget, setInvoiceTarget] = useState<AdminPaymentView | null>(null);
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
  const pendingCount = payments.filter((p) => {
    const status = adminPaymentStatus(p);
    return status === "pending" || status === "partially_paid";
  }).length;
  const collectedCents = payments
    .reduce((sum, p) => sum + (paidCents(p) ?? 0), 0);

  return (
    <section data-testid="admin-payments" className="space-y-5">
      <div className="flex flex-wrap items-center justify-end gap-2">
        <Button variant="primary" size="sm" onClick={() => setGenerateOpen(true)}>
          Generate monthly
        </Button>
      </div>

      {/* KPI strip */}
      <div className="grid gap-3 sm:grid-cols-3">
        <Metric label="Open invoices" value={String(pendingCount)} />
        <Metric label="Collected (net)" value={formatCents(collectedCents)} />
        <Metric label="Total payments" value={String(payments.length)} />
      </div>

      {isError && (
        <Card p={16} style={{ borderColor: "#fecaca", background: "#fef2f2" }}>
          <div role="alert" className="flex items-center justify-between gap-3">
            <p className="text-sm text-red-800">Failed to load payments.</p>
            <Button variant="secondary" size="sm" onClick={() => void refetch()}>Retry</Button>
          </div>
        </Card>
      )}

      <Card p={0}>
        {isLoading ? (
          <div className="p-4">
            <TableSkeleton />
          </div>
        ) : payments.length === 0 ? (
          <p className="p-8 text-center text-sm text-rally-subtle" data-testid="payments-empty">
            No payments found.
          </p>
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full min-w-[980px] text-sm" data-testid="admin-payments-table">
              <thead>
                <tr className="border-b border-rally-line text-left">
                  <Th>Payment</Th>
                  <Th>Student</Th>
                  <Th>Period</Th>
                  <Th align="right">Amount due</Th>
                  <Th align="right">Discount</Th>
                  <Th align="right">Amount paid</Th>
                  <Th>Status</Th>
                  <Th>Method</Th>
                  <Th><span className="sr-only">Actions</span></Th>
                </tr>
              </thead>
              <tbody>
                {payments.map((p) => {
                  const chip = statusChip(p.status);
                  const method = methodChip(p);
                  const rowPaidCents = paidCents(p);
                  return (
                    <tr
                      key={p.payment_id}
                      data-testid={`payment-row-${p.payment_id}`}
                      className="border-b border-rally-line/60 last:border-0"
                    >
                      <td className="px-4 py-3">
                        <div className="font-medium text-rally-ink">
                          {paymentDisplayLabel(p)}
                        </div>
                        <div className="mt-0.5 text-xs text-rally-subtle">
                          Created {new Date(p.created_at).toLocaleDateString()}
                        </div>
                      </td>
                      <td className="px-4 py-3">
                        <div className="font-display font-semibold text-rally-ink">
                          {p.student_name || "Unassigned"}
                        </div>
                        <div className="mt-0.5 text-xs text-rally-subtle">
                          Parent on file
                        </div>
                      </td>
                      <td className="px-4 py-3 text-rally-muted">{p.period || "—"}</td>
                      <td className="px-4 py-3 text-right font-mono tabular-nums">{formatCents(p.amount_cents)}</td>
                      <td className="px-4 py-3 text-right font-mono tabular-nums text-rally-subtle">
                        {p.discount_cents ? formatCents(p.discount_cents) : "—"}
                      </td>
                      <td className="px-4 py-3 text-right font-mono font-semibold tabular-nums text-rally-ink">
                        {rowPaidCents === null ? "—" : formatCents(rowPaidCents)}
                      </td>
                      <td className="px-4 py-3">
                        <Chip variant={chip.variant} label={chip.label} />
                      </td>
                      <td className="px-4 py-3">
                        {method ? <Chip variant={method.variant} label={method.label} /> : <span className="text-rally-subtle">—</span>}
                      </td>
                      <td className="px-4 py-3">
                        <PaymentActions
                          payment={p}
                          onDiscount={() => setDiscountTarget(p)}
                          onInvoice={() => setInvoiceTarget(p)}
                          onPaid={() => setPaidTarget(p)}
                          onRefund={() => setRefundTarget(p)}
                          onUndo={() => undoMutation.mutate(p.payment_id)}
                          undoPending={undoMutation.isPending}
                        />
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        )}
      </Card>

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
      <InvoiceDialog payment={invoiceTarget} onClose={() => setInvoiceTarget(null)} />
    </section>
  );
}

// ─────────────────────────────────────────────────────────────────────────────

function Metric({ label, value }: { label: string; value: string }) {
  return (
    <Card p={20}>
      <Overline>{label}</Overline>
      <div className="mt-1.5">
        <BigNum size={28}>{value}</BigNum>
      </div>
    </Card>
  );
}

function PaymentActions({
  payment,
  onDiscount,
  onInvoice,
  onPaid,
  onRefund,
  onUndo,
  undoPending,
}: {
  payment: AdminPaymentView;
  onDiscount: () => void;
  onInvoice: () => void;
  onPaid: () => void;
  onRefund: () => void;
  onUndo: () => void;
  undoPending: boolean;
}) {
  const status = adminPaymentStatus(payment);
  const isPending = status === "pending" || status === "partially_paid";
  const isPaid =
    payment.status === "succeeded" ||
    payment.status === "paid" ||
    payment.status === "partially_refunded";
  // Refund eligibility: must be paid/partial AND have remaining balance
  const refundable = isPaid && payment.refunded_cents < finalCents(payment);
  // Undo eligibility: only manual paid, not Stripe-linked
  const undoable = isPaid && !payment.stripe_linked;
  return (
    <div className="flex justify-end gap-2">
      <Button variant="secondary" size="sm" onClick={onInvoice}>Invoice</Button>
      {isPending && (
        <>
          <Button variant="secondary" size="sm" onClick={onDiscount}>Discount</Button>
          <Button variant="primary" size="sm" onClick={onPaid}>Mark paid</Button>
        </>
      )}
      {isPaid && (
        <>
          <Button
            variant="danger"
            size="sm"
            onClick={onRefund}
            disabled={!refundable}
            title={refundable ? "Issue refund" : "Already fully refunded"}
          >
            Refund
          </Button>
          <Button
            variant="secondary"
            size="sm"
            onClick={onUndo}
            disabled={!undoable || undoPending}
            title={undoable ? "Undo manual mark-paid" : "Stripe payments must be refunded"}
          >
            Undo
          </Button>
        </>
      )}
    </div>
  );
}

// ─────────────────────────────────────────────────────────────────────────────
// Dialogs (Rally-styled)
// ─────────────────────────────────────────────────────────────────────────────

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
    <RallyDialog
      open={open}
      onOpenChange={(nextOpen) => {
        if (nextOpen && !period) setPeriod(new Date().toISOString().slice(0, 7));
        if (!nextOpen) close();
        else onOpenChange(true);
      }}
      overline="Invoices"
      title="Generate monthly invoices"
      description="Creates pending invoices for active manual enrollments."
    >
      <form
        className="space-y-3"
        onSubmit={(event) => {
          event.preventDefault();
          mutation.mutate();
        }}
      >
        {error && <Alert tone="red">{error}</Alert>}
        {result && <Alert tone="green">{result}</Alert>}
        <Field label="Period" required>
          <input
            type="month"
            required
            value={period}
            onChange={(event) => setPeriod(event.target.value)}
            className={inputClass}
          />
        </Field>
        <DialogActions onCancel={close} submitLabel={mutation.isPending ? "Generating…" : "Generate"} />
      </form>
    </RallyDialog>
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
  const [reason, setReason] = useState("");
  const [error, setError] = useState<string | null>(null);
  const mutation = useMutation({
    mutationFn: () =>
      applyPaymentDiscount(payment!.payment_id, {
        discount_cents: Math.round(Number(amountInput) * 100),
        reason,
      }),
    onSuccess: () => {
      setAmountInput("");
      setReason("");
      setError(null);
      onSaved();
    },
    onError: (err: Error) => setError(err.message ?? "Discount failed."),
  });

  return (
    <RallyDialog
      open={payment !== null}
      onOpenChange={(open) => !open && onClose()}
      overline="Discount"
      title="Apply discount"
      description={payment ? `${paymentDisplayLabel(payment)} · ${formatCents(finalCents(payment))} due` : ""}
    >
      <form
        className="space-y-3"
        onSubmit={(event) => {
          event.preventDefault();
          mutation.mutate();
        }}
      >
        {error && <Alert tone="red">{error}</Alert>}
        <Field label="Discount (USD)" required>
          <input
            type="number"
            min="0"
            step="0.01"
            required
            value={amountInput}
            onChange={(event) => setAmountInput(event.target.value)}
            className={inputClass}
          />
        </Field>
        <Field label="Reason" required>
          <input
            type="text"
            required
            value={reason}
            onChange={(event) => setReason(event.target.value)}
            className={inputClass}
          />
        </Field>
        <DialogActions onCancel={onClose} submitLabel={mutation.isPending ? "Saving…" : "Save"} />
      </form>
    </RallyDialog>
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
  const [amountInput, setAmountInput] = useState("");
  const [referenceNumber, setReferenceNumber] = useState("");
  const [notes, setNotes] = useState("");
  const [error, setError] = useState<string | null>(null);
  const mutation = useMutation({
    mutationFn: () =>
      markPaymentPaid(payment!.payment_id, {
        payment_method: method as "cash" | "check" | "zelle" | "venmo" | "bank_transfer" | "other",
        amount_received_cents: amountInput ? Math.round(Number(amountInput) * 100) : undefined,
        reference_number: referenceNumber || undefined,
        notes,
      }),
    onSuccess: () => {
      setAmountInput("");
      setReferenceNumber("");
      setNotes("");
      setError(null);
      onSaved();
    },
    onError: (err: Error) => setError(err.message ?? "Mark paid failed."),
  });

  return (
    <RallyDialog
      open={payment !== null}
      onOpenChange={(open) => !open && onClose()}
      overline="Payment"
      title="Record manual payment"
      description={payment ? `${paymentDisplayLabel(payment)} for ${payment.student_name || "student"}` : ""}
    >
      <form
        className="space-y-3"
        onSubmit={(event) => {
          event.preventDefault();
          mutation.mutate();
        }}
      >
        {error && <Alert tone="red">{error}</Alert>}
        {payment && (
          <div className="grid gap-2 rounded-md border border-rally-line bg-rally-paper/50 p-3 text-sm">
            <SummaryRow label="Invoice total" value={formatCents(finalCents(payment))} />
            <SummaryRow label="Already paid" value={formatCents(payment.paid_amount_cents || 0)} />
            <SummaryRow label="Open balance" value={formatCents(payment.balance_due_cents ?? finalCents(payment))} />
          </div>
        )}
        <Field label="Amount received (USD)" required>
          <input
            type="number"
            min="0.01"
            step="0.01"
            required
            value={amountInput}
            onChange={(event) => setAmountInput(event.target.value)}
            placeholder={payment ? ((payment.balance_due_cents ?? finalCents(payment)) / 100).toFixed(2) : ""}
            className={inputClass}
          />
        </Field>
        <Field label="Payment method" required>
          <select value={method} onChange={(event) => setMethod(event.target.value)} className={inputClass}>
            <option value="cash">Cash</option>
            <option value="check">Check</option>
            <option value="zelle">Zelle</option>
            <option value="venmo">Venmo</option>
            <option value="bank_transfer">Bank transfer</option>
            <option value="other">Other</option>
          </select>
        </Field>
        <Field label="Reference">
          <input
            value={referenceNumber}
            onChange={(event) => setReferenceNumber(event.target.value)}
            className={inputClass}
          />
        </Field>
        <Field label="Notes">
          <input value={notes} onChange={(event) => setNotes(event.target.value)} className={inputClass} />
        </Field>
        <DialogActions onCancel={onClose} submitLabel={mutation.isPending ? "Saving…" : "Mark paid"} />
      </form>
    </RallyDialog>
  );
}

function InvoiceDialog({
  payment,
  onClose,
}: {
  payment: AdminPaymentView | null;
  onClose: () => void;
}) {
  const invoiceId = payment?.invoice_number || payment?.payment_id || "";
  const { data, isLoading, isError, refetch } = useQuery({
    queryKey: ["admin", "invoice-detail", invoiceId],
    queryFn: () => getAdminInvoiceDetail(invoiceId),
    enabled: Boolean(payment),
  });
  const artifactMutation = useMutation({
    mutationFn: (artifactType: "invoice_pdf" | "receipt") =>
      generateAdminInvoiceArtifact(invoiceId, artifactType),
    onSuccess: () => void refetch(),
  });

  return (
    <RallyDialog
      open={payment !== null}
      onOpenChange={(open) => !open && onClose()}
      overline="Invoice"
      title={data?.invoice_number || payment?.invoice_number || "Invoice detail"}
      description={data ? `${data.status} · ${formatCents(data.due_amount_cents)} due` : ""}
    >
      {isLoading ? (
        <TableSkeleton />
      ) : isError || !data ? (
        <Alert tone="red">Could not load invoice detail.</Alert>
      ) : (
        <div className="space-y-4 text-sm">
          <div className="grid gap-2 rounded-md border border-rally-line bg-rally-paper/50 p-3">
            <SummaryRow label="Paid" value={formatCents(data.paid_amount_cents)} />
            <SummaryRow label="Due" value={formatCents(data.due_amount_cents)} />
            <SummaryRow label="Status" value={data.status} />
          </div>
          <div>
            <div className="font-medium text-rally-ink">Lines</div>
            {data.lines.map((line) => (
              <SummaryRow key={`${line.description}-${line.amount_cents}`} label={line.description} value={formatCents(line.amount_cents)} />
            ))}
          </div>
          <div>
            <div className="font-medium text-rally-ink">Allocations</div>
            {data.allocations.length === 0 ? (
              <p className="text-rally-subtle">No payments allocated yet.</p>
            ) : (
              data.allocations.map((row) => (
                <SummaryRow key={row.payment_id} label={row.payment_id} value={formatCents(row.amount_cents)} />
              ))
            )}
          </div>
          {data.credit_usage.length > 0 && (
            <div>
              <div className="font-medium text-rally-ink">Credits used</div>
              {data.credit_usage.map((row) => (
                <SummaryRow key={row.credit_id} label={row.credit_id} value={formatCents(row.amount_cents)} />
              ))}
            </div>
          )}
          <div className="flex justify-end gap-2">
            <Button
              variant="secondary"
              size="sm"
              type="button"
              onClick={() => artifactMutation.mutate("invoice_pdf")}
              disabled={artifactMutation.isPending}
            >
              {data.invoice_pdf_artifact_id ? "Regenerate invoice" : "Generate invoice"}
            </Button>
            <Button
              variant="primary"
              size="sm"
              type="button"
              onClick={() => artifactMutation.mutate("receipt")}
              disabled={artifactMutation.isPending}
            >
              {data.receipt_artifact_id ? "Regenerate receipt" : "Generate receipt"}
            </Button>
          </div>
        </div>
      )}
    </RallyDialog>
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
    <RallyDialog
      open={payment !== null}
      onOpenChange={(open) => !open && close()}
      overline="Refund"
      title="Issue refund"
      description={payment ? `Refund up to ${formatCents(finalCents(payment) - payment.refunded_cents)}.` : ""}
    >
      {result ? (
        <div className="space-y-4">
          <Alert tone="green">Refunded {formatCents(result.refunded_cents)}.</Alert>
          <div className="flex justify-end">
            <Button
              variant="primary"
              size="sm"
              onClick={() => {
                onRefunded();
                close();
              }}
            >
              Done
            </Button>
          </div>
        </div>
      ) : (
        <form
          className="space-y-3"
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
          <Field label="Amount (USD)">
            <input
              type="number"
              min="0.01"
              step="0.01"
              value={amountInput}
              onChange={(event) => setAmountInput(event.target.value)}
              placeholder={payment ? (finalCents(payment) / 100).toFixed(2) : ""}
              className={inputClass}
            />
          </Field>
          <Field label="Reason" required>
            <input
              type="text"
              required
              value={reason}
              onChange={(event) => setReason(event.target.value)}
              className={inputClass}
            />
          </Field>
          <DialogActions onCancel={close} submitLabel={mutation.isPending ? "Processing…" : "Refund"} />
        </form>
      )}
    </RallyDialog>
  );
}

// ─────────────────────────────────────────────────────────────────────────────
// Shared helpers
// ─────────────────────────────────────────────────────────────────────────────

function RallyDialog({
  open,
  onOpenChange,
  overline,
  title,
  description,
  children,
}: {
  open: boolean;
  onOpenChange: (v: boolean) => void;
  overline: string;
  title: string;
  description: string;
  children: React.ReactNode;
}) {
  return (
    <Dialog.Root open={open} onOpenChange={onOpenChange}>
      <Dialog.Portal>
        <Dialog.Overlay className="fixed inset-0 z-50 bg-rally-ink/40" />
        <Dialog.Content className="fixed left-1/2 top-1/2 z-50 w-full max-w-md -translate-x-1/2 -translate-y-1/2 rounded-xl bg-white p-6 shadow-xl focus:outline-none">
          <Overline>{overline}</Overline>
          <Dialog.Title className="mt-1 font-display text-xl font-semibold tracking-[-0.01em]">
            {title}
          </Dialog.Title>
          {description && (
            <Dialog.Description className="mt-1 mb-4 text-sm text-rally-muted">
              {description}
            </Dialog.Description>
          )}
          {children}
        </Dialog.Content>
      </Dialog.Portal>
    </Dialog.Root>
  );
}

function DialogActions({ onCancel, submitLabel }: { onCancel: () => void; submitLabel: string }) {
  return (
    <div className="flex justify-end gap-2 pt-2">
      <Button variant="secondary" size="sm" type="button" onClick={onCancel}>Cancel</Button>
      <Button variant="primary" size="sm" type="submit">{submitLabel}</Button>
    </div>
  );
}

function Alert({ tone, children }: { tone: "green" | "red"; children: React.ReactNode }) {
  const cls =
    tone === "green"
      ? "bg-green-50 text-green-800"
      : "bg-red-50 text-red-700";
  return <p className={`rounded-md p-3 text-sm ${cls}`}>{children}</p>;
}

function SummaryRow({ label, value }: { label: string; value: string }) {
  return (
    <div className="flex items-center justify-between gap-4">
      <span className="text-rally-muted">{label}</span>
      <span className="font-mono font-medium tabular-nums text-rally-ink">{value}</span>
    </div>
  );
}

function Th({
  children,
  align = "left",
}: {
  children: React.ReactNode;
  align?: "left" | "right";
}) {
  return (
    <th
      className={`px-4 py-3 font-mono text-[10px] font-bold uppercase tracking-overline text-rally-muted ${
        align === "right" ? "text-right" : "text-left"
      }`}
    >
      {children}
    </th>
  );
}

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
      <span className="mb-1 block font-mono text-[10px] font-bold uppercase tracking-overline text-rally-muted">
        {label}
        {required && <span aria-hidden="true" className="ml-1 text-red-500">*</span>}
      </span>
      {children}
    </label>
  );
}

const inputClass =
  "w-full rounded-md border border-rally-line bg-white px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-rally-cobalt-600/30";

function TableSkeleton() {
  return (
    <div className="space-y-2">
      {[0, 1, 2, 3].map((i) => (
        <div key={i} className="h-12 animate-pulse rounded-xl bg-rally-line/40" />
      ))}
    </div>
  );
}
