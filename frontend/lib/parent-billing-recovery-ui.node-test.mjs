import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { test } from "node:test";

const paymentsPage = readFileSync(
  new URL("../app/(parent)/parent/payments/page.tsx", import.meta.url),
  "utf8",
);

const parentApi = readFileSync(new URL("api/parent.ts", import.meta.url), "utf8");

test("parent billing page exposes ledger invoice retry and card update actions", () => {
  assert.match(parentApi, /startParentInvoicePayment/);
  assert.match(paymentsPage, /startParentInvoicePayment/);
  assert.match(paymentsPage, /Pay \$\{money\(invoice\.balance_due_cents/);
  assert.match(paymentsPage, /Billing portal/);
});

test("parent billing portal hides stale Stripe customer internals", () => {
  assert.match(paymentsPage, /No such customer/);
  assert.match(paymentsPage, /BILLING_PORTAL_PREREQUISITE/);
});

test("parent payments page renders app-owned autopay visibility", () => {
  assert.match(parentApi, /autopay_enrollment_status/);
  assert.match(parentApi, /autopay_payment_method_type/);
  assert.match(paymentsPage, /autopay_enrollment_status/);
  assert.match(paymentsPage, /autopayMethodText/);
  assert.match(paymentsPage, /Bank account autopay/);
  assert.match(paymentsPage, /e\.autopay_enrollment_status === "setup_started"/);
  assert.doesNotMatch(paymentsPage, /subscription_status === "incomplete"/);
  assert.doesNotMatch(paymentsPage, /Subscribe to autopay/);
});

test("parent payments page suppresses method copy outside app-owned autopay states", () => {
  assert.match(paymentsPage, /if \(enrollment\.payment_mode !== "monthly"\) return null;/);
  assert.match(
    paymentsPage,
    /if \(!\["active", "paused", "setup_started"\]\.includes\(autopayStatus\)\) return null;/,
  );
});
