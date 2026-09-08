import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { test } from "node:test";

// The admin payments page was split into a page shell plus panels/dialogs/
// format helpers in the Rally restyle; these guards follow the code.
const read = (rel) => readFileSync(new URL(rel, import.meta.url), "utf8");
// The reconciliation lookup moved to Billing Health with the trim (spec
// 2026-09-07 §6): it answers "Stripe says this happened — did we record it?",
// which is plumbing, not a family question.
const reconciliationPanel = read(
  "../app/(admin)/admin/billing-health/ReconciliationLookupPanel.tsx",
);
const allInvoicesTab = read("../app/(admin)/admin/payments/AllInvoicesTab.tsx");
const paymentsFormat = read("../app/(admin)/admin/payments/format.ts");
const paymentsDialogs = read("../app/(admin)/admin/payments/dialogs.tsx");

test("billing health exposes the read-only reconciliation lookup", () => {
  assert.match(reconciliationPanel, /getBillingReconciliationReport/);
  assert.match(reconciliationPanel, /Read-only reconciliation/);
  assert.match(reconciliationPanel, /Stripe invoice ID/);
  assert.match(reconciliationPanel, /PaymentIntent ID/);
});

test("payments points owners at billing health instead of carrying the lookup", () => {
  assert.doesNotMatch(allInvoicesTab, /ReconciliationReportPanel|ReconciliationLookupPanel/);
  assert.match(allInvoicesTab, /billing-health-pointer/);
  assert.match(allInvoicesTab, /\/admin\/billing-health/);
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
