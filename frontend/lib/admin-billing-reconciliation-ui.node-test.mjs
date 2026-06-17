import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { test } from "node:test";

const paymentsPage = readFileSync(
  new URL("../app/(admin)/admin/payments/page.tsx", import.meta.url),
  "utf8",
);

test("admin payments page exposes read-only billing reconciliation", () => {
  assert.match(paymentsPage, /getBillingReconciliationReport/);
  assert.match(paymentsPage, /Read-only reconciliation/);
  assert.match(paymentsPage, /Stripe invoice ID/);
  assert.match(paymentsPage, /PaymentIntent ID/);
});
