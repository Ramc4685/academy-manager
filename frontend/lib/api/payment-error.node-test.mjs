import assert from "node:assert/strict";
import { test } from "node:test";

import {
  BILLING_PORTAL_PREREQUISITE,
  toPaymentErrorMessage,
  toPortalErrorMessage,
} from "./payment-error.ts";

const FALLBACK = "Something went wrong starting autopay. Please try again or contact the academy.";

function apiError(message, { code, status = 400 } = {}) {
  const err = new Error(message);
  err.status = status;
  if (code) err.code = code;
  return err;
}

test("never interpolates raw backend redirect-allowlist detail (confirmed live leak)", () => {
  const err = apiError("redirect url origin not allowed: 'http://blno.localhost:3001'", {
    code: "InvalidRedirectUrl",
  });
  const message = toPaymentErrorMessage(err, FALLBACK);
  assert.doesNotMatch(message, /blno\.localhost/);
  assert.doesNotMatch(message, /redirect url/i);
  assert.match(message, /try again or contact the academy/i);
});

test("maps InvalidRedirectUrl by code even when the message shape changes", () => {
  const err = apiError("some new internal phrasing", { code: "InvalidRedirectUrl" });
  assert.notEqual(toPaymentErrorMessage(err, FALLBACK), "some new internal phrasing");
});

test("portal mapper maps missing-Stripe-customer details to the prerequisite message", () => {
  for (const detail of [
    "No such customer: 'cus_123'",
    "parent has no Stripe customer on file",
    "autopay setup has not completed",
  ]) {
    assert.equal(toPortalErrorMessage(apiError(detail), FALLBACK), BILLING_PORTAL_PREREQUISITE);
  }
});

test("non-portal mapper never emits the circular 'start autopay first' hint", () => {
  // Confirmed live on staging: autopay start fails with a message containing
  // "autopay setup" ("Stripe connected account is not ready for autopay
  // setup"), which must NOT map to "start autopay first" on the autopay button.
  const err = apiError("Stripe connected account is not ready for autopay setup.");
  assert.equal(toPaymentErrorMessage(err, FALLBACK), FALLBACK);
});

test("maps Billing.CheckoutCreationFailed by code to academy-setup copy", () => {
  const err = apiError("Stripe connected account is not ready for autopay setup.", {
    code: "Billing.CheckoutCreationFailed",
    status: 502,
  });
  const message = toPaymentErrorMessage(err, FALLBACK);
  assert.match(message, /aren't fully set up/i);
  assert.doesNotMatch(message, /Stripe/);
  assert.equal(toPortalErrorMessage(err, FALLBACK), message);
});

test("falls back to the generic message for unknown backend detail", () => {
  assert.equal(
    toPaymentErrorMessage(apiError("mandate acceptance failed: md_987 (code 42)"), FALLBACK),
    FALLBACK,
  );
});

test("falls back for non-Error values", () => {
  assert.equal(toPaymentErrorMessage(undefined, FALLBACK), FALLBACK);
  assert.equal(toPaymentErrorMessage("string error", FALLBACK), FALLBACK);
  assert.equal(toPaymentErrorMessage({ message: "plain object" }, FALLBACK), FALLBACK);
});
