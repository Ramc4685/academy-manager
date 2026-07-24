"use client";

import { useState } from "react";
import { useMutation } from "@tanstack/react-query";

import {
  getBillingReconciliationReport,
  type BillingReconciliationReport,
} from "@/lib/api/admin";

import { Button } from "@/components/ds/button";
import { Card } from "@/components/ds/card";
import { Chip } from "@/components/ds/chip";
import { Field } from "@/components/ds/dialog-chrome";
import { BigNum, Overline } from "@/components/ds/typography";

import { formatCents } from "./format";

export function Metric({ label, value }: { label: string; value: string }) {
  return (
    <Card p={20}>
      <Overline>{label}</Overline>
      <div className="mt-1.5">
        <BigNum size={28}>{value}</BigNum>
      </div>
    </Card>
  );
}

export function ReconciliationReportPanel() {
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
