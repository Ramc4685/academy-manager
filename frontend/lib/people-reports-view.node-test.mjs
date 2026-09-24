import assert from "node:assert/strict";
import { test } from "node:test";

import {
  conversionText,
  familiesText,
  isMoneyHidden,
  normalizeInquiry,
  normalizeMoneyOwed,
} from "./people-reports-view.ts";

const MONEY = {
  as_of: "2026-09-23",
  generated_at: "2026-09-23T15:00:00Z",
  not_yet_due: {
    key: "not_yet_due",
    label: "Not yet due",
    min_days: null,
    max_days: 0,
    family_count: 2,
    total_cents: 6000,
  },
  bands: [
    { key: "days_1_30", label: "x", min_days: 1, max_days: 30, family_count: 1, total_cents: 3500 },
    {
      key: "days_31_60",
      label: "x",
      min_days: 31,
      max_days: 60,
      family_count: 1,
      total_cents: 7000,
    },
    {
      key: "days_over_60",
      label: "x",
      min_days: 61,
      max_days: null,
      family_count: 1,
      total_cents: 4000,
    },
  ],
  overdue_cents: 14500,
  overdue_family_count: 2,
  balance_cents: 20500,
  owing_family_count: 2,
};

test("money rows lead with not yet due, then the late bands in order", () => {
  const view = normalizeMoneyOwed(MONEY);
  assert.ok(view);
  assert.deepEqual(
    view.rows.map((r) => [r.key, r.label, r.familyCount, r.totalCents]),
    [
      ["not_yet_due", "Not yet due", 2, 6000],
      ["days_1_30", "1 to 30 days late", 1, 3500],
      ["days_31_60", "31 to 60 days late", 1, 7000],
      ["days_over_60", "Over 60 days late", 1, 4000],
    ],
  );
  assert.equal(view.balanceCents, 20500);
  assert.equal(view.owingFamilies, 2);
});

test("a catch-all {} or null payload is 'no report', not a crash", () => {
  assert.equal(normalizeMoneyOwed({}), null);
  assert.equal(normalizeMoneyOwed(null), null);
  assert.equal(normalizeInquiry({}), null);
  assert.equal(normalizeInquiry(undefined), null);
});

test("403 hides the money card; other errors do not", () => {
  assert.equal(isMoneyHidden({ status: 403 }), true);
  assert.equal(isMoneyHidden({ status: 503 }), false);
  assert.equal(isMoneyHidden(null), false);
});

test("inquiry rows get plain labels and a rounded conversion", () => {
  const view = normalizeInquiry({
    date_from: "2026-06-26",
    date_to: "2026-09-23",
    timezone: "America/Chicago",
    sources: [
      { source: "website", inquiries: 3, lead: 1, trial: 1, enrolled: 1, conversion_rate: 1 / 3 },
      { source: "other", inquiries: 0, lead: 0, trial: 0, enrolled: 0, conversion_rate: null },
    ],
    total: { source: "all", inquiries: 3, lead: 1, trial: 1, enrolled: 1, conversion_rate: 1 / 3 },
  });
  assert.ok(view);
  assert.deepEqual(
    view.rows.map((r) => [r.label, r.inquiries, r.conversion]),
    [
      ["Website form", 3, "33%"],
      ["Other", 0, "—"],
    ],
  );
  assert.equal(view.total.label, "All sources");
});

test("small text helpers", () => {
  assert.equal(familiesText(1), "1 family");
  assert.equal(familiesText(0), "0 families");
  assert.equal(conversionText(0.5), "50%");
  assert.equal(conversionText(Number.NaN), "—");
});
