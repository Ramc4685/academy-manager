"use client";

import { useEffect, useRef, useState } from "react";
import { useMutation } from "@tanstack/react-query";

import {
  mintPaymentIdempotencyKey,
  recordAdminInvoicePayment,
  type RecordManualPaymentResponse,
} from "@/lib/api/admin";
import { formatCents } from "@/lib/money";

import { Button } from "@/components/ds/button";
import { DialogActions, DialogError, Field, RallyModal } from "@/components/ds/dialog-chrome";

export interface RecordPaymentInvoiceOption {
  invoice_id: string;
  label: string;
  balance_due_cents: number;
}

const METHODS: { value: string; label: string }[] = [
  { value: "cash", label: "Cash" },
  { value: "check", label: "Check" },
  { value: "zelle", label: "Zelle" },
  { value: "venmo", label: "Venmo" },
  { value: "bank_transfer", label: "Bank transfer" },
  { value: "other", label: "Other" },
];

const inputClass =
  "w-full rounded-md border border-rally-line bg-white px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-rally-cobalt-600/30";

function centsToDollarInput(cents: number): string {
  return (cents / 100).toFixed(2);
}

function dollarsToCents(value: string): number {
  const parsed = Number(value.replace(/[^0-9.-]/g, ""));
  if (!Number.isFinite(parsed)) return 0;
  return Math.round(parsed * 100);
}

/**
 * Record a manual payment against one owing invoice.
 *
 * The dialog is remounted per open (see the `key` in CollectionsTab) so every
 * open starts with a fresh form and a fresh idempotency key.
 */
export function RecordPaymentDialog({
  open,
  invoices,
  initialInvoiceId,
  onClose,
  onSaved,
}: {
  open: boolean;
  invoices: RecordPaymentInvoiceOption[];
  initialInvoiceId?: string;
  onClose: () => void;
  onSaved: (result: RecordManualPaymentResponse) => void;
}) {
  const initial =
    invoices.find((inv) => inv.invoice_id === initialInvoiceId) ?? invoices[0] ?? null;
  const [invoiceId, setInvoiceId] = useState(initial?.invoice_id ?? "");
  const [amount, setAmount] = useState(initial ? centsToDollarInput(initial.balance_due_cents) : "");
  const [method, setMethod] = useState("cash");
  const [reference, setReference] = useState("");
  const [notes, setNotes] = useState("");

  // Issue #511: one idempotency key per payment INTENT (this dialog open), held
  // across retries so a resubmit after a 5xx (payment recorded, response lost)
  // replays instead of double-recording. Rotates whenever the form fields
  // change — a new payload is a new intent (the backend 422s key reuse with a
  // different payload). Same discipline as the students page dialog.
  const idempotencyKeyRef = useRef(mintPaymentIdempotencyKey());
  useEffect(() => {
    idempotencyKeyRef.current = mintPaymentIdempotencyKey();
  }, [invoiceId, amount, method, reference, notes]);

  const selected = invoices.find((inv) => inv.invoice_id === invoiceId) ?? null;
  const amountCents = dollarsToCents(amount);

  const mutation = useMutation({
    mutationFn: () =>
      recordAdminInvoicePayment(
        invoiceId,
        {
          amount_cents: amountCents,
          payment_method: method,
          reference_number: reference.trim() || null,
          notes: notes.trim(),
        },
        { idempotencyKey: idempotencyKeyRef.current },
      ),
    onSuccess: (result) => onSaved(result),
  });

  const errorMessage = mutation.error instanceof Error ? mutation.error.message : null;
  const canSubmit = Boolean(invoiceId) && amountCents > 0 && !mutation.isPending;

  return (
    <RallyModal
      open={open}
      onOpenChange={(next) => {
        if (!next) onClose();
      }}
      overline="Money"
      title="Record payment"
      description="Cash, check, Zelle or a bank transfer the family paid outside Stripe."
    >
      <form
        data-testid="record-payment-dialog"
        className="space-y-3"
        onSubmit={(event) => {
          event.preventDefault();
          if (canSubmit) mutation.mutate();
        }}
      >
        {errorMessage && <DialogError message={errorMessage} />}
        {invoices.length === 0 ? (
          <p className="text-sm text-rally-subtle" data-testid="record-payment-no-invoices">
            No open invoices to record a payment against.
          </p>
        ) : (
          <Field label="Invoice" required>
            <select
              value={invoiceId}
              onChange={(event) => {
                const next = invoices.find((inv) => inv.invoice_id === event.target.value);
                setInvoiceId(event.target.value);
                if (next) setAmount(centsToDollarInput(next.balance_due_cents));
              }}
              className={inputClass}
              data-testid="record-payment-invoice"
            >
              {invoices.map((inv) => (
                <option key={inv.invoice_id} value={inv.invoice_id}>
                  {inv.label} · {formatCents(inv.balance_due_cents)} due
                </option>
              ))}
            </select>
          </Field>
        )}
        <Field label="Amount" required>
          <input
            inputMode="decimal"
            value={amount}
            onChange={(event) => setAmount(event.target.value)}
            className={inputClass}
            data-testid="record-payment-amount"
          />
        </Field>
        {selected && amountCents > 0 && amountCents < selected.balance_due_cents && (
          <p className="text-xs text-rally-subtle">
            Partial payment — {formatCents(selected.balance_due_cents - amountCents)} will stay open.
          </p>
        )}
        <Field label="Method" required>
          <select
            value={method}
            onChange={(event) => setMethod(event.target.value)}
            className={inputClass}
            data-testid="record-payment-method"
          >
            {METHODS.map((option) => (
              <option key={option.value} value={option.value}>
                {option.label}
              </option>
            ))}
          </select>
        </Field>
        <Field label="Reference">
          <input
            value={reference}
            onChange={(event) => setReference(event.target.value)}
            placeholder="Check number, Zelle confirmation"
            className={inputClass}
            data-testid="record-payment-reference"
          />
        </Field>
        <Field label="Notes">
          <textarea
            rows={2}
            value={notes}
            onChange={(event) => setNotes(event.target.value)}
            className={inputClass}
            data-testid="record-payment-notes"
          />
        </Field>
        <DialogActions>
          <Button variant="secondary" size="sm" type="button" onClick={onClose}>
            Cancel
          </Button>
          <Button
            variant="primary"
            size="sm"
            type="submit"
            disabled={!canSubmit}
            data-testid="record-payment-submit"
          >
            {mutation.isPending ? "Recording…" : "Record payment"}
          </Button>
        </DialogActions>
      </form>
    </RallyModal>
  );
}
