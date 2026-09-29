import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { test } from "node:test";

import { policyPatch, policyToForm } from "./self-service-policy-form.ts";

const panel = readFileSync(
  new URL("../components/admin/settings/self-service-panel.tsx", import.meta.url),
  "utf8",
);

const STORED = {
  absence_notice_min_hours: 2,
  makeup_expiry_days: 30,
  makeup_requires_notice: true,
  cancellation_minimum_notice_days: 7,
  cancellation_fee_cents: 1000,
  cancellation_effective_timing: "end_of_period",
};

test("only the fields the admin changed are sent (money audit X5)", () => {
  // The whole-object PUT re-sent a cancellation fee cached minutes earlier,
  // reverting what the owner had just saved in Billing rules.
  const form = { ...policyToForm(STORED), absence_notice_min_hours: "6" };
  const { payload, errors } = policyPatch(STORED, form);
  assert.deepEqual(payload, { absence_notice_min_hours: 6 });
  assert.deepEqual(errors, {});
});

test("the cancellation fee and notice are never sent from Self-service (PR 5)", () => {
  // Billing rules is their one write path; the BFF refuses a changed value here.
  const form = policyToForm(STORED);
  assert.equal("cancellation_fee_dollars" in form, false);
  assert.equal("cancellation_minimum_notice_days" in form, false);
  const { payload } = policyPatch(STORED, { ...form, absence_notice_min_hours: "4" });
  assert.equal("cancellation_fee_cents" in payload, false);
  assert.equal("cancellation_minimum_notice_days" in payload, false);
  assert.deepEqual(policyPatch(STORED, form).payload, {});
});

test("a cleared number is an error, never a silent 0 (X20)", () => {
  const form = { ...policyToForm(STORED), makeup_expiry_days: "" };
  const { payload, errors } = policyPatch(STORED, form);
  assert.deepEqual(payload, {});
  assert.ok(errors.makeup_expiry_days);
});

test("a makeup expiry of 0 is refused: it would reject every makeup request", () => {
  const form = { ...policyToForm(STORED), makeup_expiry_days: "0" };
  assert.ok(policyPatch(STORED, form).errors.makeup_expiry_days);
});

test("junk and negative numbers are errors", () => {
  const form = {
    ...policyToForm(STORED),
    absence_notice_min_hours: "-1",
    makeup_expiry_days: "abc",
  };
  const { errors } = policyPatch(STORED, form);
  assert.ok(errors.absence_notice_min_hours);
  assert.ok(errors.makeup_expiry_days);
});

test("the panel points at Billing rules instead of editing the cancellation terms", () => {
  assert.match(panel, /cancellationTermsSummary\(query\.data\)/);
  assert.match(panel, /panel=billing-rules/);
  assert.doesNotMatch(panel, /Cancellation fee \(\$\)/);
  assert.doesNotMatch(panel, /Minimum cancellation notice/);
});

test("an out-of-bounds value already stored does not lock the other fields", () => {
  const stored = { ...STORED, makeup_expiry_days: 0 };
  const form = { ...policyToForm(stored), absence_notice_min_hours: "6" };
  const { payload, errors } = policyPatch(stored, form);
  assert.deepEqual(errors, {});
  assert.deepEqual(payload, { absence_notice_min_hours: 6 });
});
