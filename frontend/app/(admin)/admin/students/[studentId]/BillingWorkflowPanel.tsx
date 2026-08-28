"use client";

import { useEffect, useMemo, useState } from "react";
import { useMutation, useQuery } from "@tanstack/react-query";
import {
  Ban,
  CreditCard,
  DollarSign,
  FilePlus2,
  Plus,
  RefreshCw,
  Send,
  Trash2,
  Wallet,
} from "lucide-react";

import {
  addAdminInvoiceLine,
  chargeAdminInvoiceAutopay,
  deleteAdminInvoiceLine,
  getAdminInvoiceDetail,
  listBillingProducts,
  recordAdminInvoicePayment,
  sendAdminInvoice,
  voidAdminInvoice,
  type AdminInvoiceDetail,
  type SendInvoiceResponse,
} from "@/lib/api/admin";
import {
  createAdminStudentInvoice,
  type AdminStudentDetail,
  type AdminStudentPaymentSummary,
} from "@/lib/api/v2/students";
import { Button } from "@/components/ds/button";
import { Card } from "@/components/ds/card";
import { Overline } from "@/components/ds/typography";

import { DetailList } from "./DetailList";
import { formatCurrencyCents, formatDateTime, formatInvoiceDate, getErrorMessage } from "./format";
import { OPEN_BILLING_STATUSES, StatusChip } from "./StatusChip";
import {
  AddInvoiceLineDialog,
  CreateInvoiceDialog,
  RecordPaymentDialog,
  VoidInvoiceDialog,
} from "./billing-dialogs";

type BillingModal = "add-line" | "manual-payment" | "void" | "create-invoice" | null;

/**
 * Why a pay link could not be created, in admin-actionable language. A failure
 * code means the invoice email was NOT sent (backend issue #426), so the
 * message has to say so — the old copy blamed "delivery is not configured",
 * which sent admins to the email settings for a Stripe problem.
 */
const CHECKOUT_FAILURE_MESSAGES: Record<string, string> = {
  checkout_creation_failed:
    "Invoice NOT sent — Stripe rejected the payment link. The parent was not emailed. Check Stripe status, then send again.",
  connected_account_not_ready:
    "Invoice NOT sent — this academy's Stripe account can't accept charges yet. The parent was not emailed. Finish Stripe onboarding, then send again.",
  connected_accounts_not_configured:
    "Invoice NOT sent — Stripe Connect is not configured on this deployment. The parent was not emailed.",
};

function sendInvoiceMessage(result: SendInvoiceResponse): string {
  if (result.checkout_failure_code) {
    return (
      CHECKOUT_FAILURE_MESSAGES[result.checkout_failure_code] ??
      "Invoice NOT sent — the payment link could not be created. The parent was not emailed."
    );
  }
  if (result.delivery_status === "sent") {
    return result.checkout_url
      ? `Invoice sent. Checkout link: ${result.checkout_url}`
      : "Invoice sent. No online payment link — this academy collects payment directly.";
  }
  return result.checkout_url
    ? `Checkout link generated: ${result.checkout_url}`
    : "Invoice delivery is not configured.";
}

function BillingWorkflowPanel({
  student,
  active,
  onChanged,
}: {
  student: AdminStudentDetail;
  active: boolean;
  onChanged: () => void;
}) {
  const current = student.current_payment;
  const invoiceRows = useMemo(() => student.payment_history ?? [], [student.payment_history]);
  const [createdInvoiceId, setCreatedInvoiceId] = useState<string | null>(null);
  const [selectedInvoiceId, setSelectedInvoiceId] = useState<string | null>(null);
  const defaultInvoiceId =
    createdInvoiceId ??
    current?.payment_id ??
    invoiceRows.find(
      (row) => OPEN_BILLING_STATUSES.has(row.status) && row.balance_due_cents > 0,
    )?.payment_id ??
    invoiceRows[0]?.payment_id ??
    null;
  const invoiceIds = useMemo(
    () =>
      new Set([
        ...invoiceRows.map((row) => row.payment_id),
        ...(createdInvoiceId ? [createdInvoiceId] : []),
      ]),
    [createdInvoiceId, invoiceRows],
  );
  useEffect(() => {
    if (!active) return;
    if (selectedInvoiceId && invoiceIds.has(selectedInvoiceId)) return;
    setSelectedInvoiceId(defaultInvoiceId);
  }, [active, defaultInvoiceId, invoiceIds, selectedInvoiceId]);

  const invoiceId = selectedInvoiceId ?? defaultInvoiceId;
  const selectedSummary = invoiceRows.find((row) => row.payment_id === invoiceId) ?? null;
  const outstandingBalance =
    student.outstanding_balance_cents ??
    invoiceRows.reduce(
      (sum, payment) =>
        OPEN_BILLING_STATUSES.has(payment.status)
          ? sum + Math.max(payment.balance_due_cents, 0)
          : sum,
      0,
    );
  const unpaidInvoiceCount = invoiceRows.filter(
    (payment) => OPEN_BILLING_STATUSES.has(payment.status) && payment.balance_due_cents > 0,
  ).length;
  const [modal, setModal] = useState<BillingModal>(null);
  const [actionMessage, setActionMessage] = useState<string | null>(null);

  const invoiceQuery = useQuery({
    queryKey: ["admin", "billing", "invoice", invoiceId],
    queryFn: () => getAdminInvoiceDetail(invoiceId!),
    enabled: active && Boolean(invoiceId),
  });
  const productsQuery = useQuery({
    queryKey: ["admin", "billing", "products"],
    queryFn: () => listBillingProducts(),
    enabled: active && modal === "add-line",
  });

  const invoice = invoiceQuery.data;
  const status = invoice?.status ?? selectedSummary?.status ?? current?.status ?? "draft";
  const balanceDueCents =
    invoice?.balance_due_cents ??
    invoice?.due_amount_cents ??
    selectedSummary?.balance_due_cents ??
    current?.amount_cents ??
    0;
  const invoiceTotalCents =
    invoice?.total_cents ??
    (invoice
      ? invoice.due_amount_cents + invoice.paid_amount_cents
      : selectedSummary?.amount_cents ?? current?.amount_cents ?? 0);
  const paidAmountCents = invoice?.paid_amount_cents ?? selectedSummary?.paid_amount_cents ?? 0;
  const isDraft = status === "draft";
  const isVoid = status === "void";
  const isPaid = status === "paid";
  const canVoid = (status === "draft" || status === "open") && balanceDueCents === invoiceTotalCents;
  const canAddLines = Boolean(invoiceId) && !isVoid && !isPaid;
  const canRemoveLines = Boolean(invoiceId) && isDraft;
  const canSend = Boolean(invoiceId) && !isVoid && !isPaid;
  const canRecordPayment = Boolean(invoiceId) && !isDraft && !isVoid && balanceDueCents > 0;
  const canChargeAutopay = canRecordPayment;

  const refreshInvoice = () => {
    if (invoiceId) {
      void invoiceQuery.refetch();
    }
    onChanged();
  };

  const sendMutation = useMutation({
    mutationFn: () => sendAdminInvoice(invoiceId!),
    onSuccess: (result) => {
      setActionMessage(sendInvoiceMessage(result));
      refreshInvoice();
    },
  });

  const chargeMutation = useMutation({
    mutationFn: () => chargeAdminInvoiceAutopay(invoiceId!),
    onSuccess: (result) => {
      setActionMessage(
        result.success
          ? "Card charged successfully."
          : result.requires_action
            ? "Card requires parent action (3-D Secure verification)."
            : `Charge did not complete: ${result.status}`,
      );
      refreshInvoice();
    },
  });

  const deleteLineMutation = useMutation({
    mutationFn: (lineId: string) => deleteAdminInvoiceLine(invoiceId!, lineId),
    onSuccess: () => {
      setActionMessage("Line item removed.");
      refreshInvoice();
    },
  });

  const createInvoiceMutation = useMutation({
    mutationFn: (payload: { period: string; due_date: string; enrollment_id?: string | null }) =>
      createAdminStudentInvoice(student.student_id, {
        parent_id: student.parent_id,
        period: payload.period,
        due_date: payload.due_date,
        enrollment_id: payload.enrollment_id ?? null,
      }),
    onSuccess: (newInvoice) => {
      setCreatedInvoiceId(newInvoice.invoice_id);
      setSelectedInvoiceId(newInvoice.invoice_id);
      setModal(null);
      setActionMessage("Draft invoice created.");
      onChanged();
    },
  });

  const errorMessage =
    getErrorMessage(sendMutation.error) ??
    getErrorMessage(chargeMutation.error) ??
    getErrorMessage(deleteLineMutation.error) ??
    getErrorMessage(createInvoiceMutation.error) ??
    getErrorMessage(invoiceQuery.error);

  return (
    <>
      <Card p={20} data-testid="admin-student-billing-workflow">
        <div
          className="flex flex-col gap-4 border-b border-neutral-200 pb-5 lg:flex-row lg:items-start lg:justify-between"
          data-testid="admin-student-account-balance"
        >
          <div>
            <div className="flex items-center gap-2">
              <Wallet className="size-4 text-rally-muted" aria-hidden="true" />
              <Overline>Account balance</Overline>
            </div>
            <div className="mt-2 font-mono text-3xl font-semibold tabular-nums text-rally-ink">
              {formatCurrencyCents(outstandingBalance)}
            </div>
            <p className="mt-1 text-sm text-rally-muted">
              {unpaidInvoiceCount === 0
                ? "No unpaid invoices"
                : `${unpaidInvoiceCount} unpaid ${unpaidInvoiceCount === 1 ? "invoice" : "invoices"}`}
            </p>
          </div>
          <div className="flex flex-wrap gap-2">
            <Button
              size="sm"
              icon={<FilePlus2 className="size-3.5" aria-hidden="true" />}
              onClick={() => setModal("create-invoice")}
            >
              Create invoice
            </Button>
          </div>
        </div>

        {errorMessage && (
          <p role="alert" className="mt-3 rounded-md bg-red-50 px-3 py-2 text-xs text-red-700">
            {errorMessage}
          </p>
        )}
        {actionMessage && (
          <p className="mt-3 break-words rounded-md bg-blue-50 px-3 py-2 text-xs text-blue-800">
            {actionMessage}
          </p>
        )}

        <div className="mt-5 grid gap-5 lg:grid-cols-[minmax(260px,0.75fr)_minmax(0,1.45fr)]">
          <StudentInvoiceList
            invoices={invoiceRows}
            selectedInvoiceId={invoiceId}
            onSelect={(nextInvoiceId) => {
              setSelectedInvoiceId(nextInvoiceId);
              setActionMessage(null);
            }}
          />

          <section className="min-w-0" data-testid="admin-student-selected-invoice">
            <div className="flex flex-col gap-3 md:flex-row md:items-start md:justify-between">
              <div className="flex items-center gap-2">
                <CreditCard className="size-4 text-rally-muted" aria-hidden="true" />
                <Overline>Selected invoice</Overline>
              </div>
              {invoiceId && (
                <div className="flex flex-wrap gap-2">
                  <Button
                    size="sm"
                    variant="secondary"
                    icon={<Plus className="size-3.5" aria-hidden="true" />}
                    onClick={() => setModal("add-line")}
                    disabled={!canAddLines}
                    title={!canAddLines ? "Paid or void invoices cannot be edited." : undefined}
                  >
                    Add charge
                  </Button>
                  <Button
                    size="sm"
                    variant="secondary"
                    icon={
                      sendMutation.isPending ? (
                        <RefreshCw className="size-3.5 animate-spin" aria-hidden="true" />
                      ) : (
                        <Send className="size-3.5" aria-hidden="true" />
                      )
                    }
                    onClick={() => sendMutation.mutate()}
                    disabled={!canSend || sendMutation.isPending}
                  >
                    Send
                  </Button>
                  <Button
                    size="sm"
                    variant="secondary"
                    icon={<DollarSign className="size-3.5" aria-hidden="true" />}
                    onClick={() => setModal("manual-payment")}
                    disabled={!canRecordPayment}
                    title={isDraft ? "Send the invoice before recording payment." : undefined}
                  >
                    Record payment
                  </Button>
                  <Button
                    size="sm"
                    variant="secondary"
                    icon={
                      chargeMutation.isPending ? (
                        <RefreshCw className="size-3.5 animate-spin" aria-hidden="true" />
                      ) : (
                        <CreditCard className="size-3.5" aria-hidden="true" />
                      )
                    }
                    onClick={() => chargeMutation.mutate()}
                    disabled={!canChargeAutopay || chargeMutation.isPending}
                    title={
                      isDraft
                        ? "Send the invoice before charging the card."
                        : "Charge the parent's saved card now (requires a card on file)."
                    }
                  >
                    Charge card
                  </Button>
                  <Button
                    size="sm"
                    variant="danger"
                    icon={<Ban className="size-3.5" aria-hidden="true" />}
                    onClick={() => setModal("void")}
                    disabled={!canVoid}
                    title={
                      !canVoid ? "Invoices with recorded payments cannot be voided here." : undefined
                    }
                  >
                    Void
                  </Button>
                </div>
              )}
            </div>

            {!invoiceId ? (
              <p
                className="mt-4 text-sm text-rally-muted"
                data-testid="admin-student-no-current-payment"
              >
                No invoice selected.
              </p>
            ) : (
              <div className="mt-4 space-y-5" data-testid="admin-student-current-payment">
                <div className="grid gap-3 md:grid-cols-4">
                  <InvoiceMetric label="Total" value={formatCurrencyCents(invoiceTotalCents)} />
                  <InvoiceMetric label="Paid" value={formatCurrencyCents(paidAmountCents)} />
                  <InvoiceMetric label="Balance" value={formatCurrencyCents(balanceDueCents)} />
                  <div className="rounded-lg border border-neutral-200 bg-neutral-50 p-3">
                    <div className="font-mono text-[10px] font-bold uppercase tracking-overline text-rally-muted">
                      Status
                    </div>
                    <div className="mt-2">
                      <StatusChip status={status} />
                    </div>
                  </div>
                </div>

                <DetailList
                  rows={[
                    {
                      label: "Invoice",
                      value: invoice?.invoice_number ?? selectedSummary?.invoice_number ?? invoiceId,
                    },
                    { label: "Period", value: invoice?.period ?? selectedSummary?.period ?? "—" },
                    { label: "Delivery", value: invoice?.delivery_status ?? "not_sent" },
                    { label: "Sent", value: formatDateTime(invoice?.last_sent_at ?? invoice?.sent_at) },
                    {
                      label: "Session",
                      value:
                        selectedSummary?.session_id ??
                        current?.session_title ??
                        current?.session_id ??
                        "—",
                    },
                  ]}
                />

                {invoice?.email_provider_message_id ? (
                  <a
                    href={`https://resend.com/emails/${invoice.email_provider_message_id}`}
                    target="_blank"
                    rel="noopener noreferrer"
                    data-testid="admin-invoice-resend-link"
                    className="inline-flex items-center gap-1 text-xs font-medium text-rally-primary underline underline-offset-2 hover:opacity-80"
                  >
                    View delivery in Resend ↗
                  </a>
                ) : null}

                {invoiceQuery.isPending ? (
                  <div
                    className="h-20 animate-pulse rounded-lg bg-neutral-100"
                    aria-label="Loading invoice"
                  />
                ) : (
                  <InvoiceLinesTable
                    invoice={invoice}
                    canRemove={canRemoveLines}
                    removingLineId={
                      deleteLineMutation.isPending ? (deleteLineMutation.variables ?? null) : null
                    }
                    onRemove={(lineId) => deleteLineMutation.mutate(lineId)}
                  />
                )}

                <InvoiceSettlementPanel invoice={invoice} />
              </div>
            )}
          </section>
        </div>
      </Card>

      {modal === "create-invoice" && (
        <CreateInvoiceDialog
          student={student}
          pending={createInvoiceMutation.isPending}
          error={getErrorMessage(createInvoiceMutation.error)}
          onCancel={() => setModal(null)}
          onSubmit={(payload) => createInvoiceMutation.mutate(payload)}
        />
      )}
      {modal === "add-line" && invoiceId && (
        <AddInvoiceLineDialog
          invoiceId={invoiceId}
          products={productsQuery.data?.products ?? []}
          productsLoading={productsQuery.isPending}
          onCancel={() => setModal(null)}
          onSaved={(payload) => addAdminInvoiceLine(invoiceId, payload)}
          onDone={() => {
            setModal(null);
            setActionMessage("Line item added.");
            refreshInvoice();
          }}
        />
      )}
      {modal === "manual-payment" && invoiceId && (
        <RecordPaymentDialog
          balanceDueCents={balanceDueCents}
          onCancel={() => setModal(null)}
          onSaved={(payload) => recordAdminInvoicePayment(invoiceId, payload)}
          onDone={(paymentId) => {
            setModal(null);
            setActionMessage(`Payment recorded: ${paymentId}`);
            refreshInvoice();
          }}
        />
      )}
      {modal === "void" && invoiceId && (
        <VoidInvoiceDialog
          onCancel={() => setModal(null)}
          onSaved={(reason) => voidAdminInvoice(invoiceId, { reason })}
          onDone={() => {
            setModal(null);
            setActionMessage("Invoice voided.");
            refreshInvoice();
          }}
        />
      )}
    </>
  );
}

function StudentInvoiceList({
  invoices,
  selectedInvoiceId,
  onSelect,
}: {
  invoices: AdminStudentPaymentSummary[];
  selectedInvoiceId: string | null;
  onSelect: (invoiceId: string) => void;
}) {
  return (
    <section className="min-w-0" data-testid="admin-student-invoice-list">
      <div className="flex items-center justify-between gap-3">
        <Overline>Invoices</Overline>
        <span className="font-mono text-xs text-rally-muted tabular-nums">
          {invoices.length} records
        </span>
      </div>
      {invoices.length === 0 ? (
        <p className="mt-4 text-sm text-rally-muted" data-testid="admin-student-no-payments">
          No invoice records.
        </p>
      ) : (
        <div className="mt-3 divide-y divide-neutral-100 border-y border-neutral-200">
          {invoices.map((invoice) => {
            const selected = invoice.payment_id === selectedInvoiceId;
            const payable =
              OPEN_BILLING_STATUSES.has(invoice.status) && invoice.balance_due_cents > 0;
            return (
              <button
                key={invoice.payment_id}
                type="button"
                aria-pressed={selected}
                onClick={() => onSelect(invoice.payment_id)}
                className={[
                  "grid w-full grid-cols-[minmax(0,1fr)_auto] gap-3 px-2 py-3 text-left transition",
                  "hover:bg-neutral-50 focus:outline-none focus:ring-2 focus:ring-rally-cobalt-600",
                  selected ? "bg-blue-50" : "bg-white",
                ].join(" ")}
              >
                <span className="min-w-0">
                  <span className="block truncate text-sm font-medium text-rally-ink">
                    {invoice.invoice_number ?? `Invoice ${invoice.period ?? invoice.payment_id}`}
                  </span>
                  <span className="mt-1 block text-xs text-rally-muted">
                    {invoice.period ?? "No period"} · Created {formatInvoiceDate(invoice.created_at)}
                  </span>
                  {payable && (
                    <span className="mt-1 block text-xs text-rally-muted">
                      Unpaid balance {formatCurrencyCents(invoice.balance_due_cents)}
                    </span>
                  )}
                </span>
                <span className="flex flex-col items-end gap-2">
                  <StatusChip status={invoice.status} />
                  <span className="font-mono text-sm tabular-nums text-rally-ink">
                    {formatCurrencyCents(invoice.balance_due_cents)}
                  </span>
                </span>
              </button>
            );
          })}
        </div>
      )}
    </section>
  );
}

function InvoiceMetric({ label, value }: { label: string; value: string }) {
  return (
    <div className="rounded-lg border border-neutral-200 bg-neutral-50 p-3">
      <div className="font-mono text-[10px] font-bold uppercase tracking-overline text-rally-muted">
        {label}
      </div>
      <div className="mt-2 font-mono text-lg font-semibold tabular-nums text-rally-ink">
        {value}
      </div>
    </div>
  );
}

function InvoiceLinesTable({
  invoice,
  canRemove,
  removingLineId,
  onRemove,
}: {
  invoice: AdminInvoiceDetail | undefined;
  canRemove: boolean;
  removingLineId: string | null;
  onRemove: (lineId: string) => void;
}) {
  const lines = invoice?.lines ?? [];
  if (lines.length === 0) {
    return <p className="text-sm text-rally-muted">No invoice line items.</p>;
  }
  return (
    <div className="overflow-x-auto" data-testid="admin-student-invoice-lines">
      <table className="min-w-full text-left text-sm">
        <thead className="border-b border-neutral-200 text-xs uppercase tracking-overline text-rally-muted">
          <tr>
            <th className="py-2 pr-4 font-medium">Charge</th>
            <th className="py-2 pr-4 font-medium">Type</th>
            <th className="py-2 pr-4 font-medium">Qty</th>
            <th className="py-2 pr-4 font-medium">Unit</th>
            <th className="py-2 pr-4 font-medium">Amount</th>
            <th className="py-2 font-medium" />
          </tr>
        </thead>
        <tbody className="divide-y divide-neutral-100">
          {lines.map((line, index) => {
            const lineKey = line.line_id ?? `${line.description}-${index}`;
            const removable = canRemove && Boolean(line.line_id);
            return (
              <tr key={lineKey}>
                <td className="py-3 pr-4 align-top text-rally-ink">
                  {line.description}
                </td>
                <td className="py-3 pr-4 align-top text-rally-muted">
                  {line.line_type ?? "—"}
                </td>
                <td className="py-3 pr-4 align-top font-mono tabular-nums text-rally-ink">
                  {line.quantity ?? "—"}
                </td>
                <td className="py-3 pr-4 align-top font-mono tabular-nums text-rally-ink">
                  {line.unit_amount_cents == null
                    ? "—"
                    : formatCurrencyCents(line.unit_amount_cents)}
                </td>
                <td className="py-3 pr-4 align-top font-mono tabular-nums text-rally-ink">
                  {formatCurrencyCents(line.amount_cents)}
                </td>
                <td className="py-3 align-top">
                  <button
                    type="button"
                    className="inline-flex h-8 w-8 items-center justify-center rounded-md text-rally-muted hover:bg-red-50 hover:text-red-700 disabled:cursor-not-allowed disabled:opacity-40"
                    onClick={() => line.line_id && onRemove(line.line_id)}
                    disabled={!removable || removingLineId === line.line_id}
                    title={removable ? "Remove line" : "Line removal requires a draft invoice."}
                  >
                    {removingLineId === line.line_id ? (
                      <RefreshCw className="size-4 animate-spin" aria-hidden="true" />
                    ) : (
                      <Trash2 className="size-4" aria-hidden="true" />
                    )}
                    <span className="sr-only">Remove line</span>
                  </button>
                </td>
              </tr>
            );
          })}
        </tbody>
      </table>
    </div>
  );
}

function InvoiceSettlementPanel({ invoice }: { invoice: AdminInvoiceDetail | undefined }) {
  const allocations = invoice?.allocations ?? [];
  const credits = invoice?.credit_usage ?? [];
  if (allocations.length === 0 && credits.length === 0) {
    return null;
  }
  return (
    <div className="grid gap-4 md:grid-cols-2">
      <SettlementList
        label="Payment allocations"
        emptyLabel="No payment allocations"
        rows={allocations.map((item) => ({
          id: item.payment_id,
          amount: item.amount_cents,
        }))}
      />
      <SettlementList
        label="Credit usage"
        emptyLabel="No credit usage"
        rows={credits.map((item) => ({
          id: item.credit_id,
          amount: item.amount_cents,
        }))}
      />
    </div>
  );
}

function SettlementList({
  label,
  emptyLabel,
  rows,
}: {
  label: string;
  emptyLabel: string;
  rows: Array<{ id: string; amount: number }>;
}) {
  return (
    <div className="rounded-lg border border-neutral-200 bg-neutral-50 p-3">
      <div className="font-mono text-[10px] font-bold uppercase tracking-overline text-rally-muted">
        {label}
      </div>
      {rows.length === 0 ? (
        <p className="mt-2 text-xs text-rally-muted">{emptyLabel}</p>
      ) : (
        <dl className="mt-2 space-y-2 text-sm">
          {rows.map((row) => (
            <div key={row.id} className="flex items-center justify-between gap-3">
              <dt className="truncate text-rally-muted">{row.id}</dt>
              <dd className="font-mono tabular-nums text-rally-ink">
                {formatCurrencyCents(row.amount)}
              </dd>
            </div>
          ))}
        </dl>
      )}
    </div>
  );
}

export { BillingWorkflowPanel };
