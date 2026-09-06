"use client";

import { useEffect, useState } from "react";
import { useMutation } from "@tanstack/react-query";

import { Button, DialogActions, DialogError, Field, RallyModal } from "@/components/ds";
import { formatCents, parseDollarsToCents } from "@/lib/money";

export type ReasonDialogKind =
  | "void"
  | "refund"
  | "discount_once"
  | "charge_card"
  | "autopay_off"
  | "send_invoice";

const COPY: Record<
  ReasonDialogKind,
  { overline: string; title: string; description: string; submit: string }
> = {
  void: {
    overline: "Fix something",
    title: "Void invoice",
    description:
      "The invoice is cancelled and nothing is owed on it. Only unpaid invoices can be voided.",
    submit: "Void invoice",
  },
  refund: {
    overline: "Fix something",
    title: "Refund",
    description: "Money goes back to the card that paid through Stripe.",
    submit: "Issue refund",
  },
  discount_once: {
    overline: "Fix something",
    title: "One-time discount",
    description: "Reduces this invoice only. Use a recurring discount for every month.",
    submit: "Apply discount",
  },
  charge_card: {
    overline: "Fix something",
    title: "Charge card now",
    description: "Charges the card on file for this invoice's balance right away.",
    submit: "Charge card",
  },
  autopay_off: {
    overline: "Autopay",
    title: "Turn autopay off",
    description:
      "Every class stops being charged automatically. Open invoices stay open and move to the manual list.",
    submit: "Turn off",
  },
  send_invoice: {
    overline: "Invoice",
    title: "Send invoice",
    description: "Emails the invoice to the parent.",
    submit: "Send",
  },
};

export interface ReasonDialogResult {
  reason: string;
  amount_cents?: number;
  description?: string;
}

const inputClass =
  "w-full rounded-lg border border-rally-line bg-white px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-rally-cobalt-600/30";

export function ReasonDialog({
  kind,
  open,
  subject,
  maxAmountCents,
  onClose,
  onSubmit,
}: {
  kind: ReasonDialogKind;
  open: boolean;
  /** "Sep 2026 · Arjun · $60" — names what the action hits. */
  subject: string;
  /** Refund and discount cap; null for actions without an amount. */
  maxAmountCents: number | null;
  onClose: () => void;
  onSubmit: (result: ReasonDialogResult) => Promise<unknown>;
}) {
  const [reason, setReason] = useState("");
  const [amount, setAmount] = useState("");
  const [description, setDescription] = useState("");
  const wantsAmount = kind === "refund" || kind === "discount_once";
  const wantsDescription = kind === "discount_once";
  const copy = COPY[kind];

  useEffect(() => {
    if (open) {
      setReason("");
      setAmount(maxAmountCents != null ? (maxAmountCents / 100).toFixed(2) : "");
      setDescription(kind === "discount_once" ? "Discount" : "");
    }
  }, [open, kind, maxAmountCents]);

  const amountCents = wantsAmount ? parseDollarsToCents(amount) : undefined;
  const amountInvalid =
    wantsAmount &&
    (amountCents == null ||
      Number.isNaN(amountCents) ||
      amountCents <= 0 ||
      (maxAmountCents != null && amountCents > maxAmountCents));
  const mutation = useMutation({
    mutationFn: () =>
      onSubmit({
        reason: reason.trim(),
        amount_cents: amountCents,
        description: description.trim() || undefined,
      }),
    onSuccess: onClose,
  });
  const disabled = reason.trim().length === 0 || amountInvalid || mutation.isPending;

  return (
    <RallyModal
      open={open}
      onOpenChange={(v) => !v && onClose()}
      title={copy.title}
      description={copy.description}
      overline={copy.overline}
    >
      <form
        data-testid="reason-dialog"
        className="space-y-4"
        onSubmit={(e) => {
          e.preventDefault();
          if (!disabled) mutation.mutate();
        }}
      >
        <p className="text-sm text-rally-ink" data-testid="reason-subject">
          {subject}
        </p>
        {wantsAmount && (
          <Field
            label={`Amount${maxAmountCents != null ? ` (up to ${formatCents(maxAmountCents)})` : ""}`}
            required
          >
            <input
              data-testid="amount-input"
              inputMode="decimal"
              className={inputClass}
              value={amount}
              onChange={(e) => setAmount(e.target.value)}
            />
          </Field>
        )}
        {wantsDescription && (
          <Field label="Line description" required>
            <input
              data-testid="description-input"
              className={inputClass}
              value={description}
              onChange={(e) => setDescription(e.target.value)}
            />
          </Field>
        )}
        <Field label="Reason" required>
          <textarea
            data-testid="reason-input"
            rows={2}
            className={inputClass}
            value={reason}
            onChange={(e) => setReason(e.target.value)}
            placeholder="Why — this is written to the timeline"
          />
        </Field>
        {mutation.isError && <DialogError message={(mutation.error as Error).message} />}
        <DialogActions>
          <Button variant="secondary" size="sm" type="button" onClick={onClose}>
            Cancel
          </Button>
          <Button
            variant={kind === "void" || kind === "refund" ? "danger" : "primary"}
            size="sm"
            type="submit"
            disabled={disabled}
            data-testid="reason-submit"
          >
            {mutation.isPending ? "Working…" : copy.submit}
          </Button>
        </DialogActions>
      </form>
    </RallyModal>
  );
}

export function DisabledFixItem({ label, hint }: { label: string; hint: string }) {
  return (
    <div className="flex items-center justify-between rounded-lg border border-dashed border-rally-line px-3 py-2 text-sm text-rally-muted">
      <span>{label}</span>
      <span className="text-xs">{hint}</span>
    </div>
  );
}
