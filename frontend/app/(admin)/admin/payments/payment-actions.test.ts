import { readFileSync } from "node:fs";
import path from "node:path";
import { describe, expect, it } from "vitest";

import type { AdminPaymentView } from "@/lib/api/admin";

import {
  MAX_DIRECT_ROW_ACTIONS,
  paymentMenuItems,
  paymentRowActions,
  refundAmountCents,
  refundAmountInvalid,
  refundConsequence,
  refundSubject,
  refundableCents,
  splitPaymentRowActions,
} from "./dialogs";

/**
 * Issue #861 — the three money-screen defects the design critique found at
 * 1280px and 400px:
 *
 * 1. "All invoices" rendered up to five direct action buttons per row, and the
 *    resulting column pushed Status / Method / Paid-on past the right edge of
 *    the admin shell's ~944px content box at 1280. Two direct actions plus a
 *    More menu, in a width-capped sticky column, is what keeps them on screen.
 * 2. The Refund dialog never named the family and treated a BLANK amount as
 *    "refund everything still refundable" — backend
 *    `issue_refund.py` falls back to `amount - refunded` when `amount_cents`
 *    is None. An admin could move the whole balance without ever seeing whose
 *    money it was or how much.
 * 3. Collections row actions were 30px links/buttons wrapped onto two lines on
 *    a phone, under the 44px touch bar.
 *
 * These screens need auth and a live query client to render, so — following
 * `components/admin/sticky-action-columns.test.ts` and
 * `app/confirm-high-impact-actions.test.ts` — the layout halves are guarded as
 * source text and the decisions themselves are unit-tested as pure functions.
 */

/**
 * The cap on the sticky action column. Wide enough for the widest surviving
 * pair ("Invoice" + "Mark paid") and the More trigger, and ~160px narrower
 * than the five-button strip it replaces.
 */
const ACTION_COLUMN_WIDTH = "w-[232px]";

const PAYMENTS = path.resolve(__dirname);

function source(rel: string): string {
  return readFileSync(path.join(PAYMENTS, rel), "utf8");
}

const NO_OP = () => {};

const HANDLERS = {
  onDiscount: NO_OP,
  onInvoice: NO_OP,
  onPaid: NO_OP,
  onRefund: NO_OP,
  onSync: NO_OP,
  onUndo: NO_OP,
  onVoid: NO_OP,
  undoPending: false,
};

function payment(overrides: Partial<AdminPaymentView> = {}): AdminPaymentView {
  return {
    payment_id: "pmt_1",
    invoice_id: "inv_1",
    parent_id: "par_1",
    parent_name: "Rina Rao",
    student_id: "stu_1",
    student_name: "Ananya Rao",
    enrollment_id: "enr_1",
    session_id: "ses_1",
    period: "2026-09",
    amount_cents: 12000,
    discount_cents: 0,
    final_amount_cents: 12000,
    amount_received_cents: 12000,
    paid_amount_cents: 12000,
    balance_due_cents: 0,
    overpayment_credit_cents: 0,
    currency: "usd",
    status: "paid",
    refunded_cents: 0,
    invoice_number: "INV-1042",
    payment_method: "cash",
    stripe_linked: false,
    created_at: "2026-09-01T00:00:00Z",
    paid_at: "2026-09-02T00:00:00Z",
    ...overrides,
  } as AdminPaymentView;
}

const PAID = payment();
const PENDING = payment({ status: "pending", paid_amount_cents: 0, amount_received_cents: 0 });
const VOIDED = payment({ status: "voided", void_reason: "Test row" });
const FULLY_REFUNDED = payment({ status: "partially_refunded", refunded_cents: 12000 });
const STRIPE_PAID = payment({ stripe_linked: true, payment_method: "stripe_checkout" });

const SHAPES: Array<{ name: string; row: AdminPaymentView }> = [
  { name: "paid", row: PAID },
  { name: "pending", row: PENDING },
  { name: "voided", row: VOIDED },
  { name: "fully refunded", row: FULLY_REFUNDED },
  { name: "stripe paid", row: STRIPE_PAID },
];

function keysFor(row: AdminPaymentView, canGovernMoney = true) {
  const actions = paymentRowActions({ payment: row, canGovernMoney, ...HANDLERS });
  const { direct, overflow } = splitPaymentRowActions(actions);
  return {
    all: actions.map((action) => action.key),
    direct: direct.map((action) => action.key),
    overflow: overflow.map((action) => action.key),
  };
}

describe("invoice row actions collapse to two buttons plus a menu (#861)", () => {
  it.each(SHAPES)("$name keeps at most two direct buttons for an owner", ({ row }) => {
    expect(keysFor(row).direct.length).toBeLessThanOrEqual(MAX_DIRECT_ROW_ACTIONS);
  });

  it.each(SHAPES)("$name keeps at most two direct buttons for a plain admin", ({ row }) => {
    expect(keysFor(row, false).direct.length).toBeLessThanOrEqual(MAX_DIRECT_ROW_ACTIONS);
  });

  it("promotes Refund on a paid row and tucks Sync / Void / Undo away", () => {
    const { direct, overflow } = keysFor(PAID);
    expect(direct).toEqual(["invoice", "refund"]);
    expect(overflow).toEqual(["sync", "void", "undo"]);
  });

  it("promotes Mark paid on a pending row and tucks Sync / Void / Discount away", () => {
    const { direct, overflow } = keysFor(PENDING);
    expect(direct).toEqual(["invoice", "paid"]);
    expect(overflow).toEqual(["sync", "void", "discount"]);
  });

  it("leaves a voided row with Invoice alone and no menu", () => {
    const { direct, overflow } = keysFor(VOIDED);
    expect(direct).toEqual(["invoice"]);
    expect(overflow).toEqual([]);
  });

  it("splits without adding or dropping a single action", () => {
    for (const { row } of SHAPES) {
      for (const canGovernMoney of [true, false]) {
        const { all, direct, overflow } = keysFor(row, canGovernMoney);
        expect([...direct, ...overflow].sort()).toEqual([...all].sort());
      }
    }
  });

  /**
   * The phone menu and the desktop strip must keep deriving from ONE list: an
   * action offered on one layout and withheld on the other is exactly what
   * #857 removed, and eligibility (`refundable`, `undoable`,
   * `voidBlockedByStripe`) is money governance that #861 must not touch.
   */
  it.each(SHAPES)("$name offers the phone menu the same actions", ({ row }) => {
    for (const canGovernMoney of [true, false]) {
      const menu = paymentMenuItems({ payment: row, canGovernMoney, ...HANDLERS });
      expect(menu.map((item) => item.key)).toEqual(keysFor(row, canGovernMoney).all);
    }
  });

  it("keeps Refund disabled on a fully refunded row and Undo/Void off Stripe money", () => {
    const refunded = paymentRowActions({
      payment: FULLY_REFUNDED,
      canGovernMoney: true,
      ...HANDLERS,
    });
    expect(refunded.find((action) => action.key === "refund")?.disabled).toBe(true);
    const stripe = paymentRowActions({ payment: STRIPE_PAID, canGovernMoney: true, ...HANDLERS });
    expect(stripe.find((action) => action.key === "undo")?.disabled).toBe(true);
    expect(stripe.find((action) => action.key === "void")?.disabled).toBe(true);
  });
});

describe("the refund dialog names the family and demands an amount (#861)", () => {
  it("reports what is still refundable", () => {
    expect(refundableCents(PAID)).toBe(12000);
    expect(refundableCents(payment({ refunded_cents: 4000 }))).toBe(8000);
    expect(refundableCents(FULLY_REFUNDED)).toBe(0);
  });

  it("names the family, the student, the invoice and the period", () => {
    const subject = refundSubject(PAID);
    expect(subject).toContain("Rina Rao");
    expect(subject).toContain("Ananya Rao");
    expect(subject).toContain("INV-1042");
    // #892 renders the same period as a month name — still named, no longer a key.
    expect(subject).toContain("September 2026");
    expect(subject).toContain("$120.00");
  });

  it("still names a row with no student or parent on it", () => {
    const subject = refundSubject(payment({ parent_name: null, student_name: null }));
    expect(subject).toContain("Family on file");
    expect(subject.trim().length).toBeGreaterThan(0);
  });

  it("parses dollars to integer cents", () => {
    expect(refundAmountCents("60")).toBe(6000);
    expect(refundAmountCents("60.25")).toBe(6025);
    expect(refundAmountCents(" 60.25 ")).toBe(6025);
    expect(refundAmountCents("")).toBeNull();
    expect(refundAmountCents("abc")).toBeNull();
  });

  /**
   * The regression this issue exists for: blank used to reach the API as
   * `amount_cents: undefined`, which the backend reads as "everything".
   */
  it("rejects a blank, zero, negative or over-cap amount", () => {
    expect(refundAmountInvalid("", 12000)).toBe(true);
    expect(refundAmountInvalid("   ", 12000)).toBe(true);
    expect(refundAmountInvalid("0", 12000)).toBe(true);
    expect(refundAmountInvalid("-5", 12000)).toBe(true);
    expect(refundAmountInvalid("abc", 12000)).toBe(true);
    expect(refundAmountInvalid("120.01", 12000)).toBe(true);
    expect(refundAmountInvalid("120.00", 12000)).toBe(false);
    expect(refundAmountInvalid("0.01", 12000)).toBe(false);
  });

  it("prefills, offers a Full refund shortcut and never submits an undefined amount", () => {
    const src = source("dialogs.tsx");
    expect(src).toContain('data-testid="refund-subject"');
    expect(src).toContain('data-testid="refund-amount"');
    expect(src).toContain('data-testid="refund-full"');
    expect(src).toContain('data-testid="refund-submit"');
    // `amount_cents: amountInput ? Math.round(...) : undefined` was the silent
    // full refund.
    expect(src).not.toMatch(/amount_cents:\s*amountInput\s*\?/);
    expect(src).toContain("refundAmountInvalid");
  });
});

describe("money lists stay readable at 1280 and tappable at 400 (#861)", () => {
  it("caps the All invoices action column and stops forcing a 980px table", () => {
    const src = source("AllInvoicesTab.tsx");
    expect(src).not.toContain("min-w-[980px]");
    expect(src).toContain(ACTION_COLUMN_WIDTH);
    // The sticky column stays — it is what keeps the actions reachable once
    // the table does scroll (#847).
    expect(src).toContain("actionHeaderClass");
    expect(src).toContain("actionCellClass");
  });

  it("gives Collections row actions a 44px target and a phone row menu", () => {
    const src = source("buckets/CollectionsTab.tsx");
    // The WhatsApp / Message links used to hardcode a 30px height for every
    // viewport; 30px survives only as the md+ branch now.
    expect(src).not.toMatch(/inline-flex h-\[30px\]/);
    expect(src).toContain("min-h-touch");
    expect(src).toContain("OverflowMenu");
    expect(src).toContain("useIsPhone");
  });
});

/**
 * Issue #892 — the refund dialog never said what a refund does.
 *
 * "Refund up to $X" is a cap, not a consequence: it omits where the money
 * goes, when it lands and that there is no undo. The confirm was the ordinary
 * cobalt primary every harmless dialog wears.
 */
describe("the refund dialog states destination, timing and finality (#892)", () => {
  const stripePayment = {
    payment_id: "pmt_1",
    period: "2026-09",
    stripe_linked: true,
    amount_cents: 12000,
    discount_cents: 0,
    paid_amount_cents: 12000,
    refunded_cents: 0,
    status: "succeeded",
  } as AdminPaymentView;

  it("names the destination and the finality on a Stripe payment", () => {
    const line = refundConsequence(stripePayment);
    expect(line).toMatch(/original payment method/i);
    expect(line).toMatch(/cannot be undone/i);
    expect(line).toMatch(/5-10 business days/i);
  });

  it("does not promise Stripe timing for a manual payment", () => {
    const manual = { ...stripePayment, stripe_linked: false } as AdminPaymentView;
    const line = refundConsequence(manual);
    expect(line).toMatch(/original payment method/i);
    expect(line).toMatch(/cannot be undone/i);
    expect(line).not.toMatch(/business days/i);
  });

  it("reads the period as a month, not as a key", () => {
    expect(refundSubject(stripePayment)).toContain("September 2026");
    expect(refundSubject(stripePayment)).not.toContain("2026-09");
  });

  it("renders the consequence and a danger-outline confirm, not a cobalt one", () => {
    const src = source("dialogs.tsx");
    expect(src).toContain('data-testid="refund-consequence"');
    expect(src).toMatch(/variant="danger"[\s\S]{0,240}data-testid="refund-submit"/);
    expect(src).not.toMatch(/variant="primary"[\s\S]{0,240}data-testid="refund-submit"/);
  });
});

describe("Payments speaks academy, not Stripe (#892)", () => {
  it("puts the raw Stripe ids behind a disclosure on both layouts", () => {
    const src = source("AllInvoicesTab.tsx");
    expect(src).toContain("<details");
    expect(src).toContain("StripeIdDetails");
    // Two renders — the phone row and the table cell — and neither prints the
    // summary straight into the row any more.
    expect(src.match(/<StripeIdDetails /g)?.length).toBe(2);
    expect(src).not.toMatch(/>\{stripeSummary\}</);
    // The disclosure carries its own test id prefix, never the row's.
    expect(src).toMatch(/data-testid=\{`stripe-ids-\$\{paymentId\}`\}/);
    expect(src).not.toMatch(/data-testid=\{`payment-row-\$\{[^}]+\}-stripe/);
  });

  it("formats every period the invoices list shows", () => {
    const src = source("AllInvoicesTab.tsx");
    expect(src).toContain("formatPeriodLabel");
    expect(src).not.toMatch(/\{p\.period \|\| "No period"\}/);
    expect(src).not.toMatch(/\{p\.period \|\| "—"\}/);
  });

  it("formats the period on the skipped-deferral list too", () => {
    const src = source("dialogs.tsx");
    expect(src).not.toContain("{detail.billing_period}");
    expect(src).toContain("formatPeriodLabel(detail.billing_period)");
  });
});
