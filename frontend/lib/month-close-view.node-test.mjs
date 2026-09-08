import assert from "node:assert/strict";
import { test } from "node:test";

import {
  autopayRunBox,
  formatCollectionRate,
  monthCloseTiles,
  normalizeMonthClose,
  oddRows,
  warningLine,
} from "./month-close-view.ts";

function view(overrides = {}) {
  return normalizeMonthClose({
    generated_at: "2026-09-30T14:00:00Z",
    timezone: "America/Chicago",
    period: "2026-09",
    invoices: {
      generated: 42,
      emailed: 30,
      autopay_notices: 10,
      not_sent: 2,
      voided: 3,
      voided_cents: 36000,
      void_reasons: [{ reason: "duplicate", count: 3 }],
    },
    money: {
      billed_cents: 500000,
      collected_cents: 400000,
      outstanding_cents: 100000,
      collection_rate: 0.8,
    },
    autopay_run: {
      charge_on: "2026-09-08",
      charge_on_varies: false,
      has_run: true,
      scheduled: { count: 10, cents: 120000 },
      succeeded: { count: 8, cents: 96000 },
      failed: { count: 2, cents: 24000 },
      pending: { count: 0, cents: 0 },
    },
    odd: [],
    tuition_discounts: null,
    warnings: [],
    ...overrides,
  });
}

// --------------------------------------------------------------------- tiles

test("six tiles cover the invoice run and the month's money", () => {
  const tiles = monthCloseTiles(view());
  assert.deepEqual(
    tiles.map((t) => t.key),
    ["generated", "emailed", "voided", "billed", "collected", "outstanding"],
  );
  assert.equal(tiles[0].value, "42");
  assert.equal(tiles[0].hint, "2 not sent");
  // Emailed is the true sent count; the split lives in the hint because the
  // message kind is re-derived, not persisted.
  assert.equal(tiles[1].value, "40");
  assert.match(tiles[1].hint, /30 invoice emails/);
  assert.match(tiles[1].hint, /10 autopay notices/);
  assert.equal(tiles[2].value, "3");
  assert.equal(tiles[2].hint, "see reasons below");
  // Money tiles carry cents; the page formats them with the one formatCents.
  assert.equal(tiles[3].cents, 500000);
  assert.equal(tiles[4].cents, 400000);
  assert.equal(tiles[4].hint, "80% of what was billed");
  assert.equal(tiles[5].cents, 100000);
});

test("nothing voided and nothing unsent read as reassurance, not blanks", () => {
  const tiles = monthCloseTiles(
    view({
      invoices: {
        generated: 5,
        emailed: 5,
        autopay_notices: 0,
        not_sent: 0,
        voided: 0,
        voided_cents: 0,
        void_reasons: [],
      },
    }),
  );
  assert.equal(tiles[0].hint, "all sent");
  assert.equal(tiles[2].hint, "nothing voided");
});

// ---------------------------------------------------------- collection rate

test("collection rate is an em dash, never 0%, when nothing was billed", () => {
  assert.equal(formatCollectionRate(null), "—");
  assert.equal(formatCollectionRate(undefined), "—");
  assert.equal(formatCollectionRate(Number.NaN), "—");
  assert.equal(formatCollectionRate(0), "0%");
  assert.equal(formatCollectionRate(1), "100%");
  assert.equal(formatCollectionRate(0.8342), "83%");
});

test("an empty month shows a dash on the collected tile", () => {
  const tiles = monthCloseTiles(
    view({
      money: {
        billed_cents: 0,
        collected_cents: 0,
        outstanding_cents: 0,
        collection_rate: null,
      },
    }),
  );
  assert.equal(tiles[4].hint, "— of what was billed");
});

// -------------------------------------------------------------- run box

test("before the charge date the run box says what it will do", () => {
  const box = autopayRunBox(
    view({
      autopay_run: {
        charge_on: "2026-09-08",
        charge_on_varies: false,
        has_run: false,
        scheduled: { count: 10, cents: 120000 },
        succeeded: { count: 0, cents: 0 },
        failed: { count: 0, cents: 0 },
        pending: { count: 10, cents: 120000 },
      },
    }),
  );
  assert.equal(box.state, "scheduled");
  assert.equal(box.chargeOn, "2026-09-08");
  assert.equal(box.hasRun, false);
  assert.deepEqual(
    box.rows.map((r) => r.key),
    ["scheduled", "pending"],
  );
  assert.equal(box.rows[0].countLabel, "10 charges");
  assert.equal(box.rows[0].cents, 120000);
  assert.equal(box.rows[1].label, "Waiting to charge");
});

test("after the charge date the run box reports the outcome", () => {
  const box = autopayRunBox(view());
  assert.equal(box.state, "ran");
  assert.equal(box.hasRun, true);
  assert.deepEqual(
    box.rows.map((r) => r.key),
    ["scheduled", "succeeded", "failed"],
  );
  assert.equal(box.rows[2].countLabel, "2 charges");
  assert.equal(box.rows[2].cents, 24000);
});

test("a run with stragglers keeps the not-attempted tally", () => {
  const box = autopayRunBox(
    view({
      autopay_run: {
        charge_on: "2026-09-08",
        charge_on_varies: true,
        has_run: true,
        scheduled: { count: 4, cents: 40000 },
        succeeded: { count: 2, cents: 20000 },
        failed: { count: 1, cents: 10000 },
        pending: { count: 1, cents: 10000 },
      },
    }),
  );
  // A late-added enrollment gets a later due date; the box says "and later".
  assert.equal(box.state, "ran");
  assert.equal(box.chargeOnVaries, true);
  assert.equal(box.rows.at(-1).key, "pending");
  assert.equal(box.rows.at(-1).label, "Not attempted yet");
  assert.equal(box.rows[1].countLabel, "2 charges");
});

test("a month with no autopay invoice at all still renders a run box", () => {
  const box = autopayRunBox(
    view({
      autopay_run: {
        charge_on: null,
        charge_on_varies: false,
        has_run: false,
        scheduled: { count: 0, cents: 0 },
        succeeded: { count: 0, cents: 0 },
        failed: { count: 0, cents: 0 },
        pending: { count: 0, cents: 0 },
      },
    }),
  );
  assert.equal(box.state, "none");
  assert.equal(box.chargeOn, null);
  assert.equal(box.rows[0].countLabel, "0 charges");
});

// -------------------------------------------------------------- odd rows

test("all four checks render even when the backend sent none of them", () => {
  const rows = oddRows(view({ odd: [] }));
  assert.deepEqual(
    rows.map((r) => r.code),
    [
      "invoice_without_enrollment",
      "paused_family_invoiced",
      "autopay_no_card",
      "autopay_on_dead_enrollment",
    ],
  );
  assert.ok(rows.every((r) => r.count === 0 && r.expandable === false));
  assert.ok(rows.every((r) => r.label.length > 0));
});

test("a truncated odd list says how many it is showing", () => {
  const items = Array.from({ length: 20 }, (_, i) => ({
    kind: "family",
    id: `par-${i}`,
    label: `Family ${i}`,
    href: `/admin/families/par-${i}`,
  }));
  const rows = oddRows(
    view({
      odd: [
        { code: "autopay_no_card", label: "Autopay on, no card", count: 46, items },
        {
          code: "paused_family_invoiced",
          label: "Paused but invoiced",
          count: 1,
          items: [
            { kind: "invoice", id: "inv-9", label: "INV-0009", href: "/admin/payments" },
          ],
        },
      ],
    }),
  );
  const noCard = rows.find((r) => r.code === "autopay_no_card");
  assert.equal(noCard.count, 46);
  assert.equal(noCard.items.length, 20);
  assert.equal(noCard.truncatedNote, "showing 20 of 46");
  assert.equal(noCard.expandable, true);

  const paused = rows.find((r) => r.code === "paused_family_invoiced");
  assert.equal(paused.truncatedNote, null);
  assert.equal(paused.items[0].kind, "invoice");
});

// ------------------------------------------------------------- degradation

test("warnings collapse into one readable muted line", () => {
  assert.equal(warningLine(view()), null);
  assert.equal(
    warningLine(view({ warnings: ["attempts_unavailable", "discounts_unavailable"] })),
    "Some numbers are incomplete: charge attempts could not be read; the tuition discount summary could not be read.",
  );
  // An unknown code must still be nameable without a frontend release.
  assert.match(warningLine(view({ warnings: ["payouts_unavailable"] })), /payouts unavailable/);
});

test("a garbage payload normalizes to zeros instead of throwing", () => {
  const empty = normalizeMonthClose(undefined, "2026-09");
  assert.equal(empty.period, "2026-09");
  assert.equal(empty.money.collection_rate, null);
  assert.equal(empty.tuition_discounts, null);
  assert.deepEqual(empty.odd, []);
  assert.equal(monthCloseTiles(empty)[0].value, "0");
  assert.equal(autopayRunBox(empty).state, "none");
});
