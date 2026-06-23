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
  assert.match(paymentsPage, /Retry payment/);
  assert.match(paymentsPage, /Update card/);
});
