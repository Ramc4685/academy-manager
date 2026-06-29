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
