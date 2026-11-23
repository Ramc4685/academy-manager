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

test("the cancellation fee, notice and timing are never sent from Self-service (PR 5, PR 10)", () => {
  // Billing rules is their one write path; the BFF refuses a changed value here.
  const form = policyToForm(STORED);
  assert.equal("cancellation_fee_dollars" in form, false);
  assert.equal("cancellation_minimum_notice_days" in form, false);
  assert.equal("cancellation_effective_timing" in form, false);
  const { payload } = policyPatch(STORED, { ...form, absence_notice_min_hours: "4" });
  assert.equal("cancellation_fee_cents" in payload, false);
  assert.equal("cancellation_minimum_notice_days" in payload, false);
  assert.equal("cancellation_effective_timing" in payload, false);
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
  // PR 10: "Effective timing" select moved to Billing rules too.
  assert.doesNotMatch(panel, /Effective timing/);
});

test("cancellationTermsSummary states the timing Billing rules set", async () => {
  const { cancellationTermsSummary } = await import("./self-service-policy-form.ts");
  assert.match(
    cancellationTermsSummary(STORED),
    /takes effect at period end\. Set in Billing rules\.$/,
  );
  assert.match(
    cancellationTermsSummary({ ...STORED, cancellation_effective_timing: "immediate" }),
    /takes effect immediately\. Set in Billing rules\.$/,
  );
});

test("an out-of-bounds value already stored does not lock the other fields", () => {
  const stored = { ...STORED, makeup_expiry_days: 0 };
  const form = { ...policyToForm(stored), absence_notice_min_hours: "6" };
  const { payload, errors } = policyPatch(stored, form);
  assert.deepEqual(errors, {});
  assert.deepEqual(payload, { absence_notice_min_hours: 6 });
});

test("a missing switch on the stored policy defaults to on (pre-migration doc)", () => {
  const form = policyToForm(STORED);
  assert.equal(form.can_report_absence, true);
  assert.equal(form.can_claim_waitlist_offer, true);
  // Untouched switches produce no payload — same "only what changed" rule
  // as the number fields.
  assert.deepEqual(policyPatch(STORED, form).payload, {});
});

test("toggling a switch off sends only that switch", () => {
  const form = { ...policyToForm(STORED), can_request_pause: false };
  const { payload, errors } = policyPatch(STORED, form);
  assert.deepEqual(errors, {});
  assert.deepEqual(payload, { can_request_pause: false });
});

test("the settings card names all five switches and links to the trials toggle", () => {
  assert.match(panel, /What parents can do in the app/);
  assert.match(panel, /can_report_absence/);
  assert.match(panel, /can_request_makeup/);
  assert.match(panel, /can_request_pause/);
  assert.match(panel, /can_request_cancel/);
  assert.match(panel, /can_claim_waitlist_offer/);
  assert.match(panel, /Accept free trial requests/);
});

// --- Welcome-email absence policy default (Settings overhaul Phase 3 PR 10) ---

test("the welcome-email default round-trips through the form and defaults to empty", () => {
  assert.equal(policyToForm(null).welcome_email_absence_policy_default, "");
  assert.equal(
    policyToForm(STORED).welcome_email_absence_policy_default,
    "",
  );
  assert.equal(
    policyToForm({ ...STORED, welcome_email_absence_policy_default: "Call the front desk." })
      .welcome_email_absence_policy_default,
    "Call the front desk.",
  );
});

test("editing the welcome-email default sends only that field", () => {
  const form = {
    ...policyToForm(STORED),
    welcome_email_absence_policy_default: "Report absences in the parent app.",
  };
  const { payload, errors } = policyPatch(STORED, form);
  assert.deepEqual(errors, {});
  assert.deepEqual(payload, {
    welcome_email_absence_policy_default: "Report absences in the parent app.",
  });
});

test("leaving the welcome-email default alone is not a change", () => {
  const stored = { ...STORED, welcome_email_absence_policy_default: "Existing text." };
  const form = policyToForm(stored);
  assert.deepEqual(policyPatch(stored, form).payload, {});
});

test("the Absences card has the welcome-email default field", () => {
  assert.match(panel, /welcome_email_absence_policy_default/);
  assert.match(panel, /Welcome email absence &amp; makeup policy \(default\)/);
});

// --- Parent drop-off check-in (off by default) ---

const WITH_DROPOFF = {
  ...STORED,
  dropoff_checkin_enabled: false,
  dropoff_checkin_opens_minutes_before: 30,
  dropoff_checkin_closes_minutes_after: 15,
};

test("drop-off check-in defaults to off and sends only what changed", () => {
  assert.equal(policyToForm(null).dropoff_checkin_enabled, false);
  const form = {
    ...policyToForm(WITH_DROPOFF),
    dropoff_checkin_enabled: true,
    dropoff_checkin_opens_minutes_before: "20",
  };
  const { payload, errors } = policyPatch(WITH_DROPOFF, form);
  assert.deepEqual(errors, {});
  assert.deepEqual(payload, {
    dropoff_checkin_enabled: true,
    dropoff_checkin_opens_minutes_before: 20,
  });
});

test("drop-off window minutes outside the allowed range are errors", () => {
  const form = {
    ...policyToForm(WITH_DROPOFF),
    dropoff_checkin_opens_minutes_before: "61",
    dropoff_checkin_closes_minutes_after: "241",
  };
  const { payload, errors } = policyPatch(WITH_DROPOFF, form);
  assert.deepEqual(payload, {});
  assert.match(errors.dropoff_checkin_opens_minutes_before, /0 to 60/);
  assert.match(errors.dropoff_checkin_closes_minutes_after, /0 to 240/);
});

test("the parent actions card has the drop-off check-in switch and window fields", () => {
  assert.match(panel, /Drop-off check-in/);
  assert.match(panel, /dropoff_checkin_opens_minutes_before/);
  assert.match(panel, /dropoff_checkin_closes_minutes_after/);
});
