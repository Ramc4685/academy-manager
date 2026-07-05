import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { test } from "node:test";

import {
  AUTOPAY_OPTIN_LABEL,
  isEnrolledInAutopay,
  resolveEnrollAutopayChecked,
  showAutopayOptinForBalance,
  showAutopayOptinForInvoice,
} from "./parent-autopay-optin.ts";

const paymentsPage = readFileSync(
  new URL("../app/(parent)/parent/payments/page.tsx", import.meta.url),
  "utf8",
);
const parentApi = readFileSync(new URL("api/parent.ts", import.meta.url), "utf8");

function enrollment(id, status) {
  return { enrollment_id: id, autopay_enrollment_status: status };
}

function invoice(overrides = {}) {
  return { status: "open", balance_due_cents: 5000, enrollment_id: "e1", ...overrides };
}

test("checkbox label matches the approved copy exactly", () => {
  assert.equal(AUTOPAY_OPTIN_LABEL, "Enroll in autopay for future invoices");
});

test("checkbox is checked by default until explicitly unchecked", () => {
  assert.equal(resolveEnrollAutopayChecked(undefined), true);
  assert.equal(resolveEnrollAutopayChecked(true), true);
  assert.equal(resolveEnrollAutopayChecked(false), false);
});

test("enrolled statuses are active, setup_started, and paused", () => {
  for (const status of ["active", "setup_started", "paused"]) {
    assert.equal(isEnrolledInAutopay(enrollment("e1", status)), true, status);
  }
  for (const status of ["offered", "disabled", "not_offered", null, undefined, ""]) {
    assert.equal(isEnrolledInAutopay(enrollment("e1", status)), false, String(status));
  }
});

test("single-invoice checkbox hidden when the covered enrollment is already enrolled", () => {
  for (const status of ["active", "setup_started", "paused"]) {
    assert.equal(
      showAutopayOptinForInvoice(invoice(), [enrollment("e1", status)]),
      false,
      status,
    );
  }
});

test("single-invoice checkbox shown for enrollments not yet on autopay", () => {
  for (const status of ["offered", "disabled", "not_offered", null]) {
    assert.equal(
      showAutopayOptinForInvoice(invoice(), [enrollment("e1", status)]),
      true,
      String(status),
    );
  }
});

test("single-invoice checkbox defaults to shown when enrollment data is unavailable", () => {
  // Invoice has no enrollment linkage (legacy backend / non-enrollment invoice).
  assert.equal(showAutopayOptinForInvoice(invoice({ enrollment_id: null }), []), true);
  assert.equal(showAutopayOptinForInvoice(invoice({ enrollment_id: undefined }), []), true);
  // Invoice references an enrollment the page did not load.
  assert.equal(
    showAutopayOptinForInvoice(invoice({ enrollment_id: "missing" }), [enrollment("e1", "active")]),
    true,
  );
});

test("pay-all checkbox hidden when all covered enrollments are enrolled", () => {
  const invoices = [
    invoice({ enrollment_id: "e1" }),
    invoice({ enrollment_id: "e2" }),
  ];
  const enrollments = [enrollment("e1", "active"), enrollment("e2", "paused")];
  assert.equal(showAutopayOptinForBalance(invoices, enrollments), false);
});

test("pay-all checkbox shown when any open invoice's enrollment is not enrolled", () => {
  const invoices = [
    invoice({ enrollment_id: "e1" }),
    invoice({ enrollment_id: "e2" }),
  ];
  const enrollments = [enrollment("e1", "active"), enrollment("e2", "offered")];
  assert.equal(showAutopayOptinForBalance(invoices, enrollments), true);
});

test("pay-all ignores void and zero-balance invoices", () => {
  const invoices = [
    invoice({ enrollment_id: "e1", status: "void" }),
    invoice({ enrollment_id: "e2", balance_due_cents: 0 }),
  ];
  // Both invoices are outside the balance total, so nothing is covered.
  assert.equal(showAutopayOptinForBalance(invoices, [enrollment("e2", "offered")]), false);
});

test("parent API pay bodies carry enroll_autopay and invoices expose enrollment_id", () => {
  const payBodies = parentApi.match(/enroll_autopay: boolean;/g) ?? [];
  assert.equal(payBodies.length, 2, "both pay payloads declare enroll_autopay");
  assert.match(parentApi, /enrollment_id\?: string \| null;[\s\S]*?interface ParentInvoiceLine/);
});

test("payments page wires the checkbox state into both pay mutations", () => {
  assert.match(paymentsPage, /AUTOPAY_OPTIN_LABEL/);
  assert.match(paymentsPage, /showAutopayOptinForInvoice\(invoice, enrollments\)/);
  assert.match(paymentsPage, /showAutopayOptinForBalance\(invoices, enrollments\)/);
  assert.match(paymentsPage, /enroll_autopay: enrollAutopay/g);
  assert.match(paymentsPage, /resolveEnrollAutopayChecked\(invoiceAutopayOptins\[invoice\.invoice_id\]\)/);
  // Default-checked: page stores only explicit toggles and resolves undefined -> checked.
  assert.match(paymentsPage, /useState<Record<string, boolean>>\(\{\}\)/);
  assert.match(paymentsPage, /useState\(true\)/);
});

test("opted-in invoice/balance redirects carry the autopay=success poll marker", () => {
  // Codex review finding: without this, the checkout-status poll never fires
  // after a real Stripe redirect for an opted-in one-time payment, so
  // activation depended entirely on the webhook. Unchecked payments must
  // keep the plain redirect (no marker, no polling).
  assert.match(
    paymentsPage,
    /enrollAutopay\s*\?\s*`\$\{window\.location\.origin\}\/parent\/payments\?invoice=paid&autopay=success`\s*:\s*`\$\{window\.location\.origin\}\/parent\/payments\?invoice=paid`/,
  );
  assert.match(
    paymentsPage,
    /enrollAutopay\s*\?\s*`\$\{window\.location\.origin\}\/parent\/payments\?balance=paid&autopay=success`\s*:\s*`\$\{window\.location\.origin\}\/parent\/payments\?balance=paid`/,
  );
});

test("checkout-status poll treats a completed payment opt-in as terminal", () => {
  // Codex review finding: the opt-in payment-checkout status branch returns
  // "succeeded", which must be in the terminal set or the poller keeps
  // hitting the endpoint (and re-running activation) every 3s until the
  // 5-minute attempt cap instead of stopping once the payment completes.
  assert.match(paymentsPage, /CHECKOUT_POLL_TERMINAL_STATUSES = new Set\(\[[\s\S]*?"succeeded"/);
});
