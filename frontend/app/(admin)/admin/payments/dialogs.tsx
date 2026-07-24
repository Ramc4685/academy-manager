"use client";

import { useEffect, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import {
  applyPaymentDiscount,
  applyAdminInvoiceAdjustment,
  generateAdminInvoiceArtifact,
  generateMonthlyPayments,
  getAdminInvoiceDetail,
  markPaymentPaid,
  reconcileStripeBilling,
  recordAdminInvoicePayment,
  refundAdminInvoice,
  refundPayment,
  type AdminPaymentView,
  type MonthlyGenerationSkippedDetail,
  type ReconcileStripeBillingRequest,
  type RefundRequest,
} from "@/lib/api/admin";
import { queryKeys } from "@/lib/query/keys";

import { Button } from "@/components/ds/button";
import { RallyModal as RallyDialog, DialogActions, Field } from "@/components/ds/dialog-chrome";
import { TableSkeleton } from "@/components/ds/skeleton";

import {
  adminPaymentStatus,
  finalCents,
  formatCents,
  formatDate,
  invoiceActionId,
  isLedgerInvoiceRow,
  paymentDisplayLabel,
  skipReasonLabel,
} from "./format";

export function PaymentActions({
  payment,
  onDiscount,
  onInvoice,
  onPaid,
  onRefund,
  onSync,
  onUndo,
  undoPending,
}: {
  payment: AdminPaymentView;
  onDiscount: () => void;
  onInvoice: () => void;
  onPaid: () => void;
  onRefund: () => void;
  onSync: () => void;
  onUndo: () => void;
  undoPending: boolean;
}) {
  const status = adminPaymentStatus(payment);
  const invoiceRow = isLedgerInvoiceRow(payment);
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
      <Button variant="secondary" size="sm" onClick={onSync}>Sync</Button>
      {isPending && !invoiceRow && (
        <>
          <Button variant="secondary" size="sm" onClick={onDiscount}>Discount</Button>
          <Button variant="primary" size="sm" onClick={onPaid}>Mark paid</Button>
        </>
      )}
      {isPaid && !invoiceRow && (
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

export function GenerateDialog({
  open,
  onOpenChange,
  onGenerated,
}: {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  onGenerated: () => void;
}) {
  const [period, setPeriod] = useState("");
  const [result, setResult] = useState<{
    message: string;
    tone: "green" | "red";
    skippedDetails: MonthlyGenerationSkippedDetail[];
  } | null>(null);
  const [error, setError] = useState<string | null>(null);
  const mutation = useMutation({
    mutationFn: () => generateMonthlyPayments({ period }),
    onSuccess: (res) => {
      const repaired = res.repaired_orphan_keys + res.repaired_partial_invoices;
      const parts = [
        `${res.created} created`,
        `${res.skipped_existing} already complete`,
      ];
      if (repaired > 0) parts.push(`${repaired} repaired`);
      if (res.failed_repair > 0) parts.push(`${res.failed_repair} need review`);
      setResult({
        message: parts.join(", "),
        tone: res.failed_repair > 0 ? "red" : "green",
        skippedDetails: res.skipped_details ?? [],
      });
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
      description="Creates ledger invoices for active monthly enrollments."
    >
      <form
        className="space-y-3"
        onSubmit={(event) => {
          event.preventDefault();
          mutation.mutate();
        }}
      >
        {error && <Alert tone="red">{error}</Alert>}
        {result && <Alert tone={result.tone}>{result.message}</Alert>}
        {result?.skippedDetails.length ? (
          <div className="rounded border border-amber-200 bg-amber-50 p-3 text-sm text-amber-900">
            <p className="font-semibold">Skipped billing deferrals</p>
            <ul className="mt-2 space-y-2">
              {result.skippedDetails.map((detail) => (
                <li key={`${detail.enrollment_id}-${detail.reason_code}`}>
                  <span className="font-medium">
                    {detail.student_name || detail.student_id || detail.enrollment_id}
                  </span>
                  <span>
                    {" "}
                    skipped for {detail.billing_period} · {skipReasonLabel(detail.reason_code)}
                  </span>
                  <span className="block text-xs">
                    {detail.resume_on
                      ? `Resume ${formatDate(detail.resume_on)}`
                      : detail.review_on
                        ? `Review ${formatDate(detail.review_on)}`
                        : detail.expires_on
                          ? `Expires ${formatDate(detail.expires_on)}`
                          : "Needs admin review"}
                    {detail.needs_review ? " · review needed" : ""}
                  </span>
                </li>
              ))}
            </ul>
          </div>
        ) : null}
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

export function DiscountDialog({
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

export function MarkPaidDialog({
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
  const [paymentDate, setPaymentDate] = useState(() => new Date().toISOString().slice(0, 10));
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
        payment_date: paymentDate || undefined,
      }),
    onSuccess: () => {
      setAmountInput("");
      setPaymentDate(new Date().toISOString().slice(0, 10));
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
        <Field label="Payment date" required>
          <input
            type="date"
            required
            value={paymentDate}
            onChange={(event) => setPaymentDate(event.target.value)}
            className={inputClass}
          />
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

export function InvoiceDialog({
  payment,
  onClose,
}: {
  payment: AdminPaymentView | null;
  onClose: () => void;
}) {
  const invoiceId = invoiceActionId(payment);
  const queryClient = useQueryClient();
  const [manualAmountInput, setManualAmountInput] = useState("");
  const [manualMethod, setManualMethod] = useState("cash");
  const [manualReference, setManualReference] = useState("");
  const [manualNotes, setManualNotes] = useState("");
  const [adjustmentAmountInput, setAdjustmentAmountInput] = useState("");
  const [adjustmentDescription, setAdjustmentDescription] = useState("");
  const [adjustmentReason, setAdjustmentReason] = useState("");
  const [refundAmountInput, setRefundAmountInput] = useState("");
  const [refundReason, setRefundReason] = useState("");
  const [invoiceActionError, setInvoiceActionError] = useState<string | null>(null);
  const { data, isLoading, isError, refetch } = useQuery({
    queryKey: ["admin", "invoice-detail", invoiceId],
    queryFn: () => getAdminInvoiceDetail(invoiceId),
    enabled: Boolean(payment),
  });
  const refreshBillingRows = () => {
    void refetch();
    void queryClient.invalidateQueries({ queryKey: queryKeys.admin.payments() });
  };
  const artifactMutation = useMutation({
    mutationFn: (artifactType: "invoice_pdf" | "receipt") =>
      generateAdminInvoiceArtifact(invoiceId, artifactType),
    onSuccess: () => void refetch(),
  });
  const manualPaymentMutation = useMutation({
    mutationFn: () =>
      recordAdminInvoicePayment(invoiceId, {
        amount_cents: Math.round(Number(manualAmountInput) * 100),
        payment_method: manualMethod,
        reference_number: manualReference || null,
        notes: manualNotes,
      }),
    onSuccess: () => {
      setManualAmountInput("");
      setManualReference("");
      setManualNotes("");
      setInvoiceActionError(null);
      refreshBillingRows();
    },
    onError: (err: Error) => setInvoiceActionError(err.message ?? "Payment recording failed."),
  });
  const adjustmentMutation = useMutation({
    mutationFn: () =>
      applyAdminInvoiceAdjustment(invoiceId, {
        description: adjustmentDescription,
        amount_cents: Math.round(Number(adjustmentAmountInput) * 100),
        reason: adjustmentReason,
      }),
    onSuccess: () => {
      setAdjustmentAmountInput("");
      setAdjustmentDescription("");
      setAdjustmentReason("");
      setInvoiceActionError(null);
      refreshBillingRows();
    },
    onError: (err: Error) => setInvoiceActionError(err.message ?? "Adjustment failed."),
  });
  const invoiceRefundMutation = useMutation({
    mutationFn: () =>
      refundAdminInvoice(invoiceId, {
        amount_cents: refundAmountInput ? Math.round(Number(refundAmountInput) * 100) : undefined,
        reason: refundReason,
      }),
    onSuccess: () => {
      setRefundAmountInput("");
      setRefundReason("");
      setInvoiceActionError(null);
      refreshBillingRows();
    },
    onError: (err: Error) => setInvoiceActionError(err.message ?? "Refund failed."),
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
          {invoiceActionError && <Alert tone="red">{invoiceActionError}</Alert>}
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
          {data.due_amount_cents > 0 && (
            <form
              className="grid gap-3 rounded-md border border-rally-line p-3"
              onSubmit={(event) => {
                event.preventDefault();
                manualPaymentMutation.mutate();
              }}
            >
              <div className="font-medium text-rally-ink">Record manual payment</div>
              <div className="grid gap-2 sm:grid-cols-2">
                <Field label="Amount" required>
                  <input
                    type="number"
                    min="0.01"
                    step="0.01"
                    required
                    value={manualAmountInput}
                    onChange={(event) => setManualAmountInput(event.target.value)}
                    placeholder={(data.due_amount_cents / 100).toFixed(2)}
                    className={inputClass}
                  />
                </Field>
                <Field label="Method" required>
                  <select
                    required
                    value={manualMethod}
                    onChange={(event) => setManualMethod(event.target.value)}
                    className={inputClass}
                  >
                    <option value="cash">Cash</option>
                    <option value="check">Check</option>
                    <option value="zelle">Zelle</option>
                    <option value="venmo">Venmo</option>
                    <option value="bank_transfer">Bank transfer</option>
                    <option value="other">Other</option>
                  </select>
                </Field>
              </div>
              <div className="grid gap-2 sm:grid-cols-2">
                <Field label="Reference">
                  <input
                    value={manualReference}
                    onChange={(event) => setManualReference(event.target.value)}
                    className={inputClass}
                  />
                </Field>
                <Field label="Notes">
                  <input
                    value={manualNotes}
                    onChange={(event) => setManualNotes(event.target.value)}
                    className={inputClass}
                  />
                </Field>
              </div>
              <div className="flex justify-end">
                <Button
                  variant="primary"
                  size="sm"
                  type="submit"
                  disabled={manualPaymentMutation.isPending}
                >
                  {manualPaymentMutation.isPending ? "Recording..." : "Record payment"}
                </Button>
              </div>
            </form>
          )}
          <form
            className="grid gap-3 rounded-md border border-rally-line p-3"
            onSubmit={(event) => {
              event.preventDefault();
              adjustmentMutation.mutate();
            }}
          >
            <div className="font-medium text-rally-ink">Adjustment</div>
            <div className="grid gap-2 sm:grid-cols-2">
              <Field label="Amount" required>
                <input
                  type="number"
                  step="0.01"
                  required
                  value={adjustmentAmountInput}
                  onChange={(event) => setAdjustmentAmountInput(event.target.value)}
                  placeholder="-10.00"
                  className={inputClass}
                />
              </Field>
              <Field label="Description" required>
                <input
                  required
                  value={adjustmentDescription}
                  onChange={(event) => setAdjustmentDescription(event.target.value)}
                  className={inputClass}
                />
              </Field>
            </div>
            <Field label="Reason" required>
              <input
                required
                value={adjustmentReason}
                onChange={(event) => setAdjustmentReason(event.target.value)}
                className={inputClass}
              />
            </Field>
            <div className="flex justify-end">
              <Button
                variant="secondary"
                size="sm"
                type="submit"
                disabled={adjustmentMutation.isPending}
              >
                {adjustmentMutation.isPending ? "Saving..." : "Apply adjustment"}
              </Button>
            </div>
          </form>
          {data.allocations.length > 0 && (
            <form
              className="grid gap-3 rounded-md border border-rally-line p-3"
              onSubmit={(event) => {
                event.preventDefault();
                invoiceRefundMutation.mutate();
              }}
            >
              <div className="font-medium text-rally-ink">Refund allocated payment</div>
              <div className="grid gap-2 sm:grid-cols-2">
                <Field label="Amount">
                  <input
                    type="number"
                    min="0.01"
                    step="0.01"
                    value={refundAmountInput}
                    onChange={(event) => setRefundAmountInput(event.target.value)}
                    placeholder={(data.paid_amount_cents / 100).toFixed(2)}
                    className={inputClass}
                  />
                </Field>
                <Field label="Reason" required>
                  <input
                    required
                    value={refundReason}
                    onChange={(event) => setRefundReason(event.target.value)}
                    className={inputClass}
                  />
                </Field>
              </div>
              <div className="flex justify-end">
                <Button
                  variant="danger"
                  size="sm"
                  type="submit"
                  disabled={invoiceRefundMutation.isPending}
                >
                  {invoiceRefundMutation.isPending ? "Refunding..." : "Refund"}
                </Button>
              </div>
            </form>
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

export function SyncStripeDialog({
  open,
  payment,
  onClose,
  onSynced,
}: {
  open: boolean;
  payment: AdminPaymentView | null;
  onClose: () => void;
  onSynced: () => void;
}) {
  const [parentId, setParentId] = useState("");
  const [enrollmentId, setEnrollmentId] = useState("");
  const [checkoutSessionId, setCheckoutSessionId] = useState("");
  const [customerId, setCustomerId] = useState("");
  const [reason, setReason] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [result, setResult] = useState<string | null>(null);
  const mutation = useMutation({
    mutationFn: (payload: ReconcileStripeBillingRequest) => reconcileStripeBilling(payload),
    onSuccess: (res) => {
      const status = res.mismatch_state ? `Sync finished: ${res.mismatch_state}.` : "Billing sync complete.";
      setResult(status);
      setError(null);
    },
    onError: (err: Error) => setError(err.message ?? "Billing sync failed. Please try again."),
  });

  const reset = () => {
    setParentId("");
    setEnrollmentId("");
    setCheckoutSessionId("");
    setCustomerId("");
    setReason("");
    setError(null);
    setResult(null);
  };
  const close = () => {
    reset();
    onClose();
  };

  useEffect(() => {
    if (!open || !payment) return;
    setParentId(payment.parent_id);
    setEnrollmentId(payment.enrollment_id ?? "");
    setCheckoutSessionId(payment.stripe_checkout_session_id ?? "");
    setCustomerId(payment.stripe_customer_id ?? "");
  }, [open, payment]);

  return (
    <RallyDialog
      open={open}
      onOpenChange={(nextOpen) => !nextOpen && close()}
      overline="Stripe"
      title="Sync billing from Stripe"
      description="Fetches the live checkout session and updates billing records after tenant validation."
    >
      {result ? (
        <div className="space-y-4">
          <Alert tone="green">{result}</Alert>
          <div className="flex justify-end">
            <Button
              variant="primary"
              size="sm"
              onClick={() => {
                onSynced();
                reset();
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
            mutation.mutate({
              parent_id: parentId.trim(),
              enrollment_id: enrollmentId.trim(),
              stripe_checkout_session_id: checkoutSessionId.trim(),
              stripe_customer_id: customerId.trim() || null,
              reason: reason.trim(),
            });
          }}
        >
          {error && <Alert tone="red">{error}</Alert>}
          <Field label="Parent ID" required>
            <input
              required
              value={parentId}
              onChange={(event) => setParentId(event.target.value)}
              className={inputClass}
            />
          </Field>
          <Field label="Enrollment ID" required>
            <input
              required
              value={enrollmentId}
              onChange={(event) => setEnrollmentId(event.target.value)}
              className={inputClass}
            />
          </Field>
          <Field label="Stripe Checkout Session ID" required>
            <input
              required
              value={checkoutSessionId}
              onChange={(event) => setCheckoutSessionId(event.target.value)}
              className={inputClass}
              placeholder="cs_live_..."
            />
          </Field>
          <Field label="Stripe Customer ID">
            <input
              value={customerId}
              onChange={(event) => setCustomerId(event.target.value)}
              className={inputClass}
              placeholder="cus_..."
            />
          </Field>
          <Field label="Audit reason" required>
            <textarea
              required
              minLength={8}
              rows={3}
              value={reason}
              onChange={(event) => setReason(event.target.value)}
              className={`${inputClass} min-h-24 py-2`}
              placeholder="Backfill confirmed Stripe payment for ..."
            />
          </Field>
          <DialogActions onCancel={close} submitLabel={mutation.isPending ? "Syncing..." : "Sync"} />
        </form>
      )}
    </RallyDialog>
  );
}

export function RefundDialog({
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

const inputClass =
  "w-full rounded-md border border-rally-line bg-white px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-rally-cobalt-600/30";
