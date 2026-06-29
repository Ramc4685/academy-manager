"use client";

/**
 * Admin payments — Rally restyle.
 *
 * Rally MONEY route for payments. Preserves: generate-monthly,
 * apply-discount, mark-paid, undo-paid, refund. Refund disabled when
 * payment isn't eligible.
 */

import { useEffect, useMemo, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import * as Dialog from "@radix-ui/react-dialog";

import {
  applyPaymentDiscount,
  applyAdminInvoiceAdjustment,
  generateAdminInvoiceArtifact,
  generateMonthlyPayments,
  getAdminInvoiceDetail,
  getBillingReconciliationReport,
  listBillingWebhookEvents,
  listAdminPayments,
  markPaymentPaid,
  reconcileStripeBilling,
  recordAdminInvoicePayment,
  refundAdminInvoice,
  refundPayment,
  undoPaymentPaid,
  type AdminPaymentStatus,
  type AdminPaymentView,
  type BillingReconciliationReport,
  type MonthlyGenerationSkippedDetail,
  type ReconcileStripeBillingRequest,
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

function formatDate(value: string): string {
  return new Date(`${value}T00:00:00`).toLocaleDateString(undefined, {
    month: "short",
    day: "numeric",
    year: "numeric",
  });
}

function skipReasonLabel(value: string): string {
  return value.replaceAll("_", " ");
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

function stripeIdSummary(payment: AdminPaymentView): string | null {
  const ids = [
    payment.stripe_checkout_session_id,
    payment.stripe_invoice_id,
    payment.stripe_payment_intent_id,
    payment.stripe_subscription_id,
  ].filter(Boolean);
  if (ids.length === 0) return null;
  return ids.join(" · ");
}

function reconciliationLabel(payment: AdminPaymentView): string | null {
  if (payment.reconciliation_status) {
    return payment.reconciliation_status.replaceAll("_", " ");
  }
  if (
    (payment.status === "pending" || payment.status === "partially_paid") &&
    payment.stripe_linked
  ) {
    return "Stripe linked, app ledger pending";
  }
  return null;
}

function isLedgerInvoiceRow(payment: AdminPaymentView): boolean {
  return payment.payment_method === "invoice" || payment.payment_method === "stripe";
}

function invoiceActionId(payment: AdminPaymentView | null): string {
  return payment?.invoice_id || payment?.payment_id || "";
}

function sessionFilterKey(payment: AdminPaymentView): string {
  return payment.session_id || "__none__";
}

function sessionFilterLabel(value: string): string {
  return value === "__none__" ? "No session" : value;
}

export default function AdminPaymentsPage() {
  const [refundTarget, setRefundTarget] = useState<AdminPaymentView | null>(null);
  const [paidTarget, setPaidTarget] = useState<AdminPaymentView | null>(null);
  const [discountTarget, setDiscountTarget] = useState<AdminPaymentView | null>(null);
  const [invoiceTarget, setInvoiceTarget] = useState<AdminPaymentView | null>(null);
  const [syncTarget, setSyncTarget] = useState<AdminPaymentView | null>(null);
  const [syncOpen, setSyncOpen] = useState(false);
  const [generateOpen, setGenerateOpen] = useState(false);
  const [periodFilter, setPeriodFilter] = useState("all");
  const [sessionFilter, setSessionFilter] = useState("all");
  const queryClient = useQueryClient();

  const { data, isLoading, isError, refetch } = useQuery({
    queryKey: queryKeys.admin.payments(),
    queryFn: () => listAdminPayments(),
  });
  const webhookQueueQuery = useQuery({
    queryKey: ["admin", "billing-webhooks", "failed-quarantined"],
    queryFn: () => listBillingWebhookEvents({ limit: 5 }),
  });

  const undoMutation = useMutation({
    mutationFn: (paymentId: string) => undoPaymentPaid(paymentId),
    onSuccess: () => void queryClient.invalidateQueries({ queryKey: queryKeys.admin.payments() }),
  });

  const payments = useMemo(() => data?.payments ?? [], [data?.payments]);
  const periodOptions = useMemo(
    () =>
      Array.from(new Set(payments.map((payment) => payment.period).filter(Boolean)))
        .sort()
        .reverse() as string[],
    [payments],
  );
  const sessionOptions = useMemo(
    () =>
      Array.from(new Set(payments.map((payment) => sessionFilterKey(payment)))).sort((a, b) =>
        sessionFilterLabel(a).localeCompare(sessionFilterLabel(b)),
      ),
    [payments],
  );
  const filteredPayments = useMemo(
    () =>
      payments.filter((payment) => {
        if (periodFilter !== "all" && payment.period !== periodFilter) return false;
        if (sessionFilter !== "all" && sessionFilterKey(payment) !== sessionFilter) return false;
        return true;
      }),
    [payments, periodFilter, sessionFilter],
  );
  const webhookEvents = webhookQueueQuery.data?.events ?? [];
  const pendingCount = payments.filter((p) => {
    const status = adminPaymentStatus(p);
    return status === "pending" || status === "partially_paid";
  }).length;
  const failedPaymentCount = payments.filter((p) => adminPaymentStatus(p) === "failed").length;
  const collectedCents = payments.reduce((sum, p) => sum + (paidCents(p) ?? 0), 0);

  return (
    <section data-testid="admin-payments" className="space-y-5">
      <div className="flex flex-wrap items-center justify-end gap-2">
        <Button
          variant="secondary"
          size="sm"
          onClick={() => {
            setSyncTarget(null);
            setSyncOpen(true);
          }}
        >
          Sync Stripe
        </Button>
        <Button variant="primary" size="sm" onClick={() => setGenerateOpen(true)}>
          Generate monthly
        </Button>
      </div>

      {/* KPI strip */}
      <div className="grid gap-3 sm:grid-cols-3">
        <Metric label="Open invoices" value={String(pendingCount)} />
        <Metric label="Failed payments" value={String(failedPaymentCount)} />
        <Metric label="Collected (net)" value={formatCents(collectedCents)} />
      </div>

      <Card p={16}>
        <div className="flex flex-col gap-3 sm:flex-row sm:items-start sm:justify-between">
          <div>
            <Overline>Recovery</Overline>
            <h2 className="mt-1 font-display text-lg font-semibold text-rally-ink">
              Failed webhook queue
            </h2>
          </div>
          <Button
            variant="secondary"
            size="sm"
            onClick={() => void webhookQueueQuery.refetch()}
            disabled={webhookQueueQuery.isFetching}
          >
            Refresh
          </Button>
        </div>
        {webhookQueueQuery.isError ? (
          <p className="mt-3 text-sm text-red-700">Could not load webhook recovery queue.</p>
        ) : webhookEvents.length === 0 ? (
          <p className="mt-3 text-sm text-rally-subtle">No failed or quarantined webhooks.</p>
        ) : (
          <div className="mt-4 divide-y divide-rally-line">
            {webhookEvents.map((event) => (
              <div key={event.event_id} className="grid gap-2 py-3 text-sm sm:grid-cols-[1fr_auto]">
                <div>
                  <div className="flex flex-wrap items-center gap-2">
                    <span className="font-medium text-rally-ink">{event.event_type}</span>
                    <Chip
                      variant={event.status === "quarantined" ? "failed" : "pending"}
                      label={event.status.toUpperCase()}
                    />
                  </div>
                  <p className="mt-1 max-w-2xl text-rally-subtle">
                    {event.error_message || "No error detail recorded."}
                  </p>
                </div>
                <div className="font-mono text-xs text-rally-subtle sm:text-right">
                  <div>{event.event_id}</div>
                  {event.object_id && <div>{event.object_id}</div>}
                </div>
              </div>
            ))}
          </div>
        )}
      </Card>

      <ReconciliationReportPanel />

      <Card p={16}>
        <div className="grid gap-3 md:grid-cols-[minmax(180px,240px)_minmax(180px,280px)_1fr_auto] md:items-end">
          <Field label="Month">
            <select
              value={periodFilter}
              onChange={(event) => setPeriodFilter(event.target.value)}
              className={inputClass}
            >
              <option value="all">All months</option>
              {periodOptions.map((period) => (
                <option key={period} value={period}>
                  {period}
                </option>
              ))}
            </select>
          </Field>
          <Field label="Session">
            <select
              value={sessionFilter}
              onChange={(event) => setSessionFilter(event.target.value)}
              className={inputClass}
            >
              <option value="all">All sessions</option>
              {sessionOptions.map((session) => (
                <option key={session} value={session}>
                  {sessionFilterLabel(session)}
                </option>
              ))}
            </select>
          </Field>
          <div className="text-sm text-rally-subtle md:pb-2">
            Showing {filteredPayments.length} of {payments.length} records
          </div>
          <Button
            variant="secondary"
            size="sm"
            onClick={() => {
              setPeriodFilter("all");
              setSessionFilter("all");
            }}
            disabled={periodFilter === "all" && sessionFilter === "all"}
          >
            Reset
          </Button>
        </div>
      </Card>

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
        ) : filteredPayments.length === 0 ? (
          <p className="p-8 text-center text-sm text-rally-subtle" data-testid="payments-filter-empty">
            No payments match these filters.
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
                {filteredPayments.map((p) => {
                  const chip = statusChip(p.status);
                  const method = methodChip(p);
                  const rowPaidCents = paidCents(p);
                  const stripeSummary = stripeIdSummary(p);
                  const reconciliation = reconciliationLabel(p);
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
                        {(stripeSummary || reconciliation) && (
                          <div className="mt-1 max-w-[280px] space-y-0.5 text-xs text-rally-subtle">
                            {stripeSummary && (
                              <div className="truncate font-mono" title={stripeSummary}>
                                {stripeSummary}
                              </div>
                            )}
                            {reconciliation && (
                              <div className="font-medium text-amber-700">
                                {reconciliation}
                              </div>
                            )}
                          </div>
                        )}
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
                          onSync={() => {
                            setSyncTarget(p);
                            setSyncOpen(true);
                          }}
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
      <SyncStripeDialog
        open={syncOpen}
        payment={syncTarget}
        onClose={() => {
          setSyncOpen(false);
          setSyncTarget(null);
        }}
        onSynced={() => {
          setSyncOpen(false);
          setSyncTarget(null);
          void queryClient.invalidateQueries({ queryKey: queryKeys.admin.payments() });
        }}
      />
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

function ReconciliationReportPanel() {
  const [stripeInvoiceId, setStripeInvoiceId] = useState("");
  const [paymentIntentId, setPaymentIntentId] = useState("");
  const [error, setError] = useState<string | null>(null);
  const canRun = Boolean(stripeInvoiceId.trim() || paymentIntentId.trim());
  const mutation = useMutation({
    mutationFn: () =>
      getBillingReconciliationReport({
        stripe_invoice_id: stripeInvoiceId.trim() || null,
        payment_intent_id: paymentIntentId.trim() || null,
      }),
    onSuccess: () => setError(null),
    onError: (err: Error) => setError(err.message ?? "Reconciliation failed."),
  });
  const report = mutation.data;

  return (
    <Card p={16}>
      <div>
        <Overline>Reconciliation</Overline>
        <h2 className="mt-1 font-display text-lg font-semibold text-rally-ink">
          Read-only reconciliation
        </h2>
      </div>
      <form
        className="mt-4 grid gap-3 lg:grid-cols-[1fr_1fr_auto]"
        onSubmit={(event) => {
          event.preventDefault();
          if (!canRun) {
            setError("An invoice ID or PaymentIntent ID is required.");
            return;
          }
          mutation.mutate();
        }}
      >
        <Field label="Stripe invoice ID">
          <input
            value={stripeInvoiceId}
            onChange={(event) => setStripeInvoiceId(event.target.value)}
            className={inputClass}
            placeholder="in_..."
          />
        </Field>
        <Field label="PaymentIntent ID">
          <input
            value={paymentIntentId}
            onChange={(event) => setPaymentIntentId(event.target.value)}
            className={inputClass}
            placeholder="pi_..."
          />
        </Field>
        <div className="flex items-end">
          <Button
            variant="secondary"
            size="sm"
            type="submit"
            disabled={!canRun || mutation.isPending}
          >
            {mutation.isPending ? "Checking..." : "Run report"}
          </Button>
        </div>
      </form>
      {error && <div className="mt-3"><Alert tone="red">{error}</Alert></div>}
      {report && <ReconciliationReportSummary report={report} />}
    </Card>
  );
}

function ReconciliationReportSummary({ report }: { report: BillingReconciliationReport }) {
  const checkedAt = new Date(report.checked_at).toLocaleString();
  const manualReviewCandidates = Array.isArray(report.manual_review_candidates)
    ? report.manual_review_candidates
    : [];
  return (
    <div className="mt-4 space-y-3 text-sm">
      <div className="flex flex-wrap items-center gap-2">
        <Chip
          variant={report.result === "MATCH" ? "paid" : "failed"}
          label={report.result.replaceAll("_", " ")}
        />
        <span className="text-rally-subtle">Checked {checkedAt}</span>
      </div>
      <div className="grid gap-2 rounded-md border border-rally-line bg-rally-paper/50 p-3 md:grid-cols-2">
        <SummaryRow label="Stripe invoice" value={report.stripe_invoice_id || "—"} />
        <SummaryRow label="PaymentIntent" value={report.payment_intent_id || "—"} />
        <SummaryRow label="Stripe customer" value={report.stripe_customer_id || "—"} />
        <SummaryRow label="Ledger invoice" value={report.local_invoice_id || "—"} />
        <SummaryRow label="Ledger payment" value={report.ledger_payment_id || "—"} />
        <SummaryRow label="Payment allocation" value={report.payment_allocation_id || "—"} />
      </div>
      {report.mismatches.length === 0 ? (
        <p className="text-sm text-rally-subtle">No mismatches found.</p>
      ) : (
        <div className="divide-y divide-rally-line rounded-md border border-rally-line">
          {report.mismatches.map((mismatch, index) => (
            <div key={`${mismatch.code}-${index}`} className="grid gap-1 p-3 sm:grid-cols-[180px_1fr]">
              <div className="font-mono text-xs font-bold uppercase text-rally-ink">
                {mismatch.code}
              </div>
              <div>
                <p className="text-rally-ink">{mismatch.message}</p>
                <p className="mt-1 font-mono text-xs text-rally-subtle">
                  Stripe: {String(mismatch.stripe_value ?? "—")} · Local:{" "}
                  {String(mismatch.local_value ?? "—")}
                </p>
              </div>
            </div>
          ))}
        </div>
      )}
      {manualReviewCandidates.length > 0 && (
        <div className="divide-y divide-rally-line rounded-md border border-amber-200 bg-amber-50/50">
          <div className="p-3">
            <div className="font-mono text-xs font-bold uppercase tracking-[0.18em] text-amber-800">
              Manual review candidates
            </div>
          </div>
          {manualReviewCandidates.map((candidate) => (
            <div key={candidate.invoice_id} className="grid gap-1 p-3 sm:grid-cols-[180px_1fr]">
              <div className="font-mono text-xs font-bold uppercase text-rally-ink">
                {candidate.invoice_id}
              </div>
              <div>
                <p className="text-rally-ink">
                  {formatCents(candidate.amount_cents)} open balance for parent{" "}
                  {candidate.parent_id}
                  {candidate.period ? ` (${candidate.period})` : ""}
                </p>
                <p className="mt-1 text-xs text-rally-subtle">{candidate.reason}</p>
              </div>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}

function PaymentActions({
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

function InvoiceDialog({
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

function SyncStripeDialog({
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
        <Dialog.Content className="fixed left-1/2 top-1/2 z-50 max-h-[90vh] w-full max-w-md -translate-x-1/2 -translate-y-1/2 overflow-y-auto rounded-xl bg-white p-6 shadow-xl focus:outline-none">
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
