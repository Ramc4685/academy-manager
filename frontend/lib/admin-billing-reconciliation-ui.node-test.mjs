import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { test } from "node:test";

// The admin payments page was split into a page shell plus panels/dialogs/
// format helpers in the Rally restyle; these guards follow the code.
const read = (rel) => readFileSync(new URL(rel, import.meta.url), "utf8");
const reconciliationPanel = read("../app/(admin)/admin/payments/ReconciliationReportPanel.tsx");
const paymentsFormat = read("../app/(admin)/admin/payments/format.ts");
const paymentsDialogs = read("../app/(admin)/admin/payments/dialogs.tsx");

test("admin payments page exposes read-only billing reconciliation", () => {
  assert.match(reconciliationPanel, /getBillingReconciliationReport/);
  assert.match(reconciliationPanel, /Read-only reconciliation/);
  assert.match(reconciliationPanel, /Stripe invoice ID/);
  assert.match(reconciliationPanel, /PaymentIntent ID/);
});

test("admin payments page hides legacy payment mutations for ledger invoice rows", () => {
  assert.match(paymentsFormat, /function isLedgerInvoiceRow/);
  assert.match(paymentsDialogs, /isPending && !invoiceRow/);
  assert.match(paymentsDialogs, /isPaid && !invoiceRow/);
});

test("admin payments invoice dialog exposes invoice-native admin actions", () => {
  assert.match(paymentsDialogs, /recordAdminInvoicePayment/);
  assert.match(paymentsDialogs, /applyAdminInvoiceAdjustment/);
  assert.match(paymentsDialogs, /refundAdminInvoice/);
});
