import { createElement } from "react";
import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it } from "vitest";

import type { FamilyManualPayment } from "@/lib/api/admin-families";

import { FixSomethingPanel, fixItemsFor } from "./FixSomethingPanel";
import { manualPaymentSummary, voidPaymentExplainer } from "./family-view";

describe("fixItemsFor (#928 card charges are owner-only)", () => {
  it("hides every money-moving fix, card charge included, from a non-owner", () => {
    const kinds = fixItemsFor(false).map((it) => it.kind);
    expect(kinds).not.toContain("charge_card");
    expect(kinds).not.toContain("void");
    expect(kinds).not.toContain("refund");
    expect(kinds).not.toContain("discount_once");
  });

  it("offers the owner the card charge alongside void, refund and discount", () => {
    expect(fixItemsFor(true).map((it) => it.kind)).toEqual([
      "void",
      "refund",
      "discount_once",
      "charge_card",
    ]);
  });
});

// The production case: a $300 Zelle recorded on one $60 invoice.
const ZELLE: FamilyManualPayment = {
  payment_id: "manual-k1",
  method: "zelle",
  amount_cents: 30_000,
  paid_at: "2026-10-29T15:00:00Z",
  allocations: [{ invoice_id: "inv-oct", amount_cents: 6_000 }],
  credit_cents: 24_000,
  credit_spent_cents: 0,
  void_blocked_reason: null,
};
const INVOICES = [{ invoice_id: "inv-oct", period: "2026-10" }];

describe("manualPaymentSummary", () => {
  it("names the payment, the invoice it paid and the credit it minted", () => {
    expect(manualPaymentSummary(ZELLE, INVOICES)).toEqual({
      title: "Zelle $300.00 · Oct 29",
      detail: "Paid Oct 2026 $60.00 · $240.00 account credit",
      blocked: null,
    });
  });

  it("falls back to the invoice id when the invoice is not on this page", () => {
    expect(manualPaymentSummary(ZELLE, []).detail).toContain("inv-oct $60.00");
  });

  it("explains why a payment whose credit was spent cannot be voided", () => {
    const spent = {
      ...ZELLE,
      credit_spent_cents: 6_000,
      void_blocked_reason: "credit_spent" as const,
    };
    expect(manualPaymentSummary(spent, INVOICES).blocked).toMatch(
      /\$60\.00 of its credit already paid/,
    );
  });
});

describe("voidPaymentExplainer", () => {
  it("says it voids the payment, not an invoice, and cancels the minted credit", () => {
    const text = voidPaymentExplainer(ZELLE);
    expect(text).toContain("voids the payment, not an invoice");
    expect(text).toContain("balance reopens");
    expect(text).toContain("$240.00 account credit it created is cancelled");
  });
});

function render(isOwner: boolean, payments: FamilyManualPayment[]): string {
  return renderToStaticMarkup(
    createElement(FixSomethingPanel, {
      invoices: [],
      manualPayments: payments,
      isOwner,
      onPick: () => undefined,
      onVoidPayment: () => undefined,
    }),
  );
}

describe("FixSomethingPanel manual payments", () => {
  it("lists an owner's voidable manual payment with a Void payment button", () => {
    const html = render(true, [ZELLE]);
    expect(html).toContain('data-testid="manual-payment-manual-k1"');
    expect(html).toContain("Void payment");
    expect(html).toContain("not an invoice");
    expect(html).not.toMatch(
      /data-testid="void-payment-manual-k1"[^>]*disabled/,
    );
  });

  it("disables the void when the payment's credit was already spent", () => {
    const html = render(true, [
      {
        ...ZELLE,
        credit_spent_cents: 6_000,
        void_blocked_reason: "credit_spent",
      },
    ]);
    expect(html).toMatch(
      /<button[^>]*disabled[^>]*data-testid="void-payment-manual-k1"|data-testid="void-payment-manual-k1"[^>]*disabled/,
    );
  });

  it("shows a non-owner nothing to void", () => {
    expect(render(false, [ZELLE])).not.toContain("manual-payment-");
  });
});
