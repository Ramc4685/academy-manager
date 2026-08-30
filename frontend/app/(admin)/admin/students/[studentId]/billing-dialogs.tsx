"use client";

import { type ReactNode, useEffect, useRef, useState } from "react";
import { useMutation } from "@tanstack/react-query";
import { RefreshCw } from "lucide-react";

import {
  type AddInvoiceLineRequest,
  type AdminBillingProductView,
  type RecordManualPaymentRequest,
  mintPaymentIdempotencyKey,
} from "@/lib/api/admin";
import { type AdminStudentDetail } from "@/lib/api/v2/students";
import { Button } from "@/components/ds/button";
import { Modal } from "@/components/ds/modal";

import { centsToDollarInput, dollarsToCents, formatCurrencyCents, getErrorMessage } from "./format";
import { Field } from "./StudentEditForm";

function CreateInvoiceDialog({
  student,
  pending,
  error,
  onCancel,
  onSubmit,
}: {
  student: AdminStudentDetail;
  pending: boolean;
  error: string | null | undefined;
  onCancel: () => void;
  onSubmit: (payload: { period: string; due_date: string; enrollment_id?: string | null }) => void;
}) {
  const [period, setPeriod] = useState(() => new Date().toISOString().slice(0, 7));
  const [dueDate, setDueDate] = useState(() => new Date().toISOString().slice(0, 10));
  const [enrollmentId, setEnrollmentId] = useState("");
  const sessions = student.enrolled_sessions ?? [];

  return (
    <BillingDialogFrame title="Create draft invoice" onCancel={onCancel}>
      {error && <BillingDialogError message={error} />}
      <div className="space-y-3">
        <Field label="Period" htmlFor="billing-create-period">
          <input
            id="billing-create-period"
            type="month"
            value={period}
            onChange={(event) => setPeriod(event.target.value)}
            className="h-10 w-full rounded-md border border-neutral-200 bg-white px-3 text-sm text-rally-base outline-none focus:border-rally-cobalt-600 focus:ring-2 focus:ring-rally-cobalt-600/15"
          />
        </Field>
        <Field label="Due date" htmlFor="billing-create-due-date">
          <input
            id="billing-create-due-date"
            type="date"
            value={dueDate}
            onChange={(event) => setDueDate(event.target.value)}
            className="h-10 w-full rounded-md border border-neutral-200 bg-white px-3 text-sm text-rally-base outline-none focus:border-rally-cobalt-600 focus:ring-2 focus:ring-rally-cobalt-600/15"
          />
        </Field>
        <Field label="Enrollment" htmlFor="billing-create-enrollment">
          <select
            id="billing-create-enrollment"
            value={enrollmentId}
            onChange={(event) => setEnrollmentId(event.target.value)}
            className="h-10 w-full rounded-md border border-neutral-200 bg-white px-3 text-sm text-rally-base outline-none focus:border-rally-cobalt-600 focus:ring-2 focus:ring-rally-cobalt-600/15"
          >
            <option value="">No enrollment link</option>
            {sessions.map((session) => (
              <option key={session.enrollment_id} value={session.enrollment_id}>
                {session.session_title}
              </option>
            ))}
          </select>
        </Field>
      </div>
      <BillingDialogActions onCancel={onCancel}>
        <Button
          size="sm"
          disabled={!period || !dueDate || pending}
          icon={pending ? <RefreshCw className="size-3.5 animate-spin" aria-hidden="true" /> : undefined}
          onClick={() =>
            onSubmit({
              period,
              due_date: dueDate,
              enrollment_id: enrollmentId || null,
            })
          }
        >
          {pending ? "Creating..." : "Create invoice"}
        </Button>
      </BillingDialogActions>
    </BillingDialogFrame>
  );
}

function AddInvoiceLineDialog({
  invoiceId,
  products,
  productsLoading,
  onCancel,
  onSaved,
  onDone,
}: {
  invoiceId: string;
  products: AdminBillingProductView[];
  productsLoading: boolean;
  onCancel: () => void;
  onSaved: (payload: AddInvoiceLineRequest) => Promise<unknown>;
  onDone: () => void;
}) {
  const [productId, setProductId] = useState("");
  const [description, setDescription] = useState("");
  const [lineType, setLineType] = useState("fee");
  const [quantity, setQuantity] = useState("1");
  const [unitAmount, setUnitAmount] = useState("");

  useEffect(() => {
    const selected = products.find((product) => product.product_id === productId);
    if (!selected) return;
    setDescription(selected.name);
    setLineType(selected.line_type);
    setUnitAmount(centsToDollarInput(selected.default_unit_amount_cents));
  }, [productId, products]);

  const mutation = useMutation({
    mutationFn: () =>
      onSaved({
        product_id: productId || null,
        description: description.trim(),
        line_type: lineType.trim(),
        quantity: Number.parseInt(quantity, 10),
        unit_amount_cents: dollarsToCents(unitAmount),
      }),
    onSuccess: onDone,
  });
  const canSubmit =
    description.trim().length > 0 &&
    lineType.trim().length > 0 &&
    Number.parseInt(quantity, 10) > 0 &&
    dollarsToCents(unitAmount) >= 0;

  return (
    <BillingDialogFrame title="Add invoice charge" onCancel={onCancel}>
      {getErrorMessage(mutation.error) && (
        <BillingDialogError message={getErrorMessage(mutation.error)!} />
      )}
      <div className="space-y-3">
        <Field label="Product" htmlFor={`billing-product-${invoiceId}`}>
          <select
            id={`billing-product-${invoiceId}`}
            value={productId}
            onChange={(event) => setProductId(event.target.value)}
            className="h-10 w-full rounded-md border border-neutral-200 bg-white px-3 text-sm text-rally-base outline-none focus:border-rally-cobalt-600 focus:ring-2 focus:ring-rally-cobalt-600/15"
          >
            <option value="">{productsLoading ? "Loading products..." : "Custom charge"}</option>
            {products.map((product) => (
              <option key={product.product_id} value={product.product_id}>
                {product.name} - {formatCurrencyCents(product.default_unit_amount_cents)}
              </option>
            ))}
          </select>
        </Field>
        <Field label="Description" htmlFor={`billing-line-description-${invoiceId}`}>
          <input
            id={`billing-line-description-${invoiceId}`}
            value={description}
            onChange={(event) => setDescription(event.target.value)}
            className="h-10 w-full rounded-md border border-neutral-200 bg-white px-3 text-sm text-rally-base outline-none focus:border-rally-cobalt-600 focus:ring-2 focus:ring-rally-cobalt-600/15"
          />
        </Field>
        <div className="grid gap-3 sm:grid-cols-3">
          <Field label="Type" htmlFor={`billing-line-type-${invoiceId}`}>
            <input
              id={`billing-line-type-${invoiceId}`}
              value={lineType}
              onChange={(event) => setLineType(event.target.value)}
              className="h-10 w-full rounded-md border border-neutral-200 bg-white px-3 text-sm text-rally-base outline-none focus:border-rally-cobalt-600 focus:ring-2 focus:ring-rally-cobalt-600/15"
            />
          </Field>
          <Field label="Qty" htmlFor={`billing-line-quantity-${invoiceId}`}>
            <input
              id={`billing-line-quantity-${invoiceId}`}
              type="number"
              min="1"
              step="1"
              value={quantity}
              onChange={(event) => setQuantity(event.target.value)}
              className="h-10 w-full rounded-md border border-neutral-200 bg-white px-3 text-sm text-rally-base outline-none focus:border-rally-cobalt-600 focus:ring-2 focus:ring-rally-cobalt-600/15"
            />
          </Field>
          <Field label="Unit amount" htmlFor={`billing-line-amount-${invoiceId}`}>
            <input
              id={`billing-line-amount-${invoiceId}`}
              inputMode="decimal"
              value={unitAmount}
              onChange={(event) => setUnitAmount(event.target.value)}
              className="h-10 w-full rounded-md border border-neutral-200 bg-white px-3 text-sm text-rally-base outline-none focus:border-rally-cobalt-600 focus:ring-2 focus:ring-rally-cobalt-600/15"
              placeholder="0.00"
            />
          </Field>
        </div>
      </div>
      <BillingDialogActions onCancel={onCancel}>
        <Button
          size="sm"
          disabled={!canSubmit || mutation.isPending}
          icon={mutation.isPending ? <RefreshCw className="size-3.5 animate-spin" aria-hidden="true" /> : undefined}
          onClick={() => mutation.mutate()}
        >
          {mutation.isPending ? "Adding..." : "Add charge"}
        </Button>
      </BillingDialogActions>
    </BillingDialogFrame>
  );
}

function RecordPaymentDialog({
  balanceDueCents,
  onCancel,
  onSaved,
  onDone,
}: {
  balanceDueCents: number;
  onCancel: () => void;
  onSaved: (
    payload: RecordManualPaymentRequest,
    options: { idempotencyKey: string },
  ) => Promise<{ payment_id: string }>;
  onDone: (paymentId: string) => void;
}) {
  const [amount, setAmount] = useState(() => centsToDollarInput(balanceDueCents));
  const [method, setMethod] = useState("cash");
  const [referenceNumber, setReferenceNumber] = useState("");
  const [notes, setNotes] = useState("");
  // Issue #511: one idempotency key per payment INTENT (this dialog open), held
  // across retries so a resubmit after a 5xx (payment recorded, response lost)
  // replays instead of double-recording. Rotates when the form fields change —
  // a new payload is a new intent (the backend 422s key reuse with a different
  // payload). The dialog unmounts on success, so a re-open mints a fresh key.
  const idempotencyKeyRef = useRef(mintPaymentIdempotencyKey());
  useEffect(() => {
    idempotencyKeyRef.current = mintPaymentIdempotencyKey();
  }, [amount, method, referenceNumber, notes]);
  const mutation = useMutation({
    mutationFn: () =>
      onSaved(
        {
          amount_cents: dollarsToCents(amount),
          payment_method: method,
          reference_number: referenceNumber.trim() || null,
          notes: notes.trim(),
        },
        { idempotencyKey: idempotencyKeyRef.current },
      ),
    onSuccess: (result) => onDone(result.payment_id),
  });
  const amountCents = dollarsToCents(amount);

  return (
    <BillingDialogFrame title="Record manual payment" onCancel={onCancel}>
      {getErrorMessage(mutation.error) && (
        <BillingDialogError message={getErrorMessage(mutation.error)!} />
      )}
      <div className="space-y-3">
        <Field label="Amount" htmlFor="billing-payment-amount">
          <input
            id="billing-payment-amount"
            inputMode="decimal"
            value={amount}
            onChange={(event) => setAmount(event.target.value)}
            className="h-10 w-full rounded-md border border-neutral-200 bg-white px-3 text-sm text-rally-base outline-none focus:border-rally-cobalt-600 focus:ring-2 focus:ring-rally-cobalt-600/15"
          />
        </Field>
        <Field label="Method" htmlFor="billing-payment-method">
          <select
            id="billing-payment-method"
            value={method}
            onChange={(event) => setMethod(event.target.value)}
            className="h-10 w-full rounded-md border border-neutral-200 bg-white px-3 text-sm text-rally-base outline-none focus:border-rally-cobalt-600 focus:ring-2 focus:ring-rally-cobalt-600/15"
          >
            <option value="cash">Cash</option>
            <option value="check">Check</option>
            <option value="zelle">Zelle</option>
            <option value="venmo">Venmo</option>
            <option value="bank_transfer">Bank transfer</option>
            <option value="other">Other</option>
          </select>
        </Field>
        <Field label="Reference" htmlFor="billing-payment-reference">
          <input
            id="billing-payment-reference"
            value={referenceNumber}
            onChange={(event) => setReferenceNumber(event.target.value)}
            className="h-10 w-full rounded-md border border-neutral-200 bg-white px-3 text-sm text-rally-base outline-none focus:border-rally-cobalt-600 focus:ring-2 focus:ring-rally-cobalt-600/15"
          />
        </Field>
        <Field label="Notes" htmlFor="billing-payment-notes">
          <textarea
            id="billing-payment-notes"
            rows={3}
            value={notes}
            onChange={(event) => setNotes(event.target.value)}
            className="w-full rounded-md border border-neutral-200 bg-white px-3 py-2 text-sm text-rally-base outline-none focus:border-rally-cobalt-600 focus:ring-2 focus:ring-rally-cobalt-600/15"
          />
        </Field>
      </div>
      <BillingDialogActions onCancel={onCancel}>
        <Button
          size="sm"
          disabled={amountCents <= 0 || mutation.isPending}
          icon={mutation.isPending ? <RefreshCw className="size-3.5 animate-spin" aria-hidden="true" /> : undefined}
          onClick={() => mutation.mutate()}
        >
          {mutation.isPending ? "Recording..." : "Record payment"}
        </Button>
      </BillingDialogActions>
    </BillingDialogFrame>
  );
}

function VoidInvoiceDialog({
  onCancel,
  onSaved,
  onDone,
}: {
  onCancel: () => void;
  onSaved: (reason: string) => Promise<unknown>;
  onDone: () => void;
}) {
  const [reason, setReason] = useState("");
  const mutation = useMutation({
    mutationFn: () => onSaved(reason.trim()),
    onSuccess: onDone,
  });

  return (
    <BillingDialogFrame title="Void invoice" onCancel={onCancel}>
      {getErrorMessage(mutation.error) && (
        <BillingDialogError message={getErrorMessage(mutation.error)!} />
      )}
      <Field label="Reason" htmlFor="billing-void-reason">
        <textarea
          id="billing-void-reason"
          rows={3}
          value={reason}
          onChange={(event) => setReason(event.target.value)}
          className="w-full rounded-md border border-neutral-200 bg-white px-3 py-2 text-sm text-rally-base outline-none focus:border-rally-cobalt-600 focus:ring-2 focus:ring-rally-cobalt-600/15"
          required
        />
      </Field>
      <BillingDialogActions onCancel={onCancel}>
        <Button
          size="sm"
          variant="danger"
          disabled={reason.trim().length === 0 || mutation.isPending}
          icon={mutation.isPending ? <RefreshCw className="size-3.5 animate-spin" aria-hidden="true" /> : undefined}
          onClick={() => mutation.mutate()}
        >
          {mutation.isPending ? "Voiding..." : "Void invoice"}
        </Button>
      </BillingDialogActions>
    </BillingDialogFrame>
  );
}

function BillingDialogFrame({
  title,
  children,
  onCancel,
}: {
  title: string;
  children: ReactNode;
  onCancel: () => void;
}) {
  return (
    <Modal open onClose={onCancel} size="lg" title={title}>
      {children}
    </Modal>
  );
}

function BillingDialogActions({
  children,
  onCancel,
}: {
  children: ReactNode;
  onCancel: () => void;
}) {
  return (
    <div className="mt-5 flex justify-end gap-2">
      <Button variant="ghost" size="sm" onClick={onCancel}>
        Cancel
      </Button>
      {children}
    </div>
  );
}

function BillingDialogError({ message }: { message: string }) {
  return <p className="mb-3 rounded-md bg-red-50 px-3 py-2 text-xs text-red-700">{message}</p>;
}

export {
  CreateInvoiceDialog,
  AddInvoiceLineDialog,
  RecordPaymentDialog,
  VoidInvoiceDialog,
  BillingDialogFrame,
  BillingDialogActions,
  BillingDialogError,
};
