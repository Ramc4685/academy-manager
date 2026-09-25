import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { test } from "node:test";

import {
  boundsMessage,
  canSave,
  diffForm,
  editableRows,
  inputToValue,
  rowToInput,
  saveSummary,
  toForm,
  turnsLateFeeOn,
} from "./billing-rules-form.ts";
import { formatCents, parseDollarsToCents } from "./money.ts";

const MONEY = { format: formatCents, parse: parseDollarsToCents };

const panel = readFileSync(
  new URL("../components/admin/settings/billing-rules-panel.tsx", import.meta.url),
  "utf8",
);
const settingsPage = readFileSync(
  new URL("../app/(admin)/admin/settings/page.tsx", import.meta.url),
  "utf8",
);
const tabs = readFileSync(
  new URL("../components/admin/settings/settings-tabs.tsx", import.meta.url),
  "utf8",
);

function editable(key, value, unit, min, max, label = key) {
  return {
    key,
    label,
    editable: true,
    value,
    unit,
    min_value: min,
    max_value: max,
    display: null,
    detail: null,
  };
}

function fixed(key, display) {
  return {
    key,
    label: key,
    editable: false,
    value: null,
    unit: null,
    min_value: null,
    max_value: null,
    display,
    detail: "because",
  };
}

function view() {
  return {
    groups: [
      {
        key: "monthly_invoicing",
        title: "Monthly invoicing",
        note: null,
        rows: [
          editable("billing_day", 1, "day_of_month", 1, 28, "Invoice day of month"),
          editable("invoice_due_days", 7, "days", 0, 60, "Days until due"),
          fixed("autopay_charge_time", "09:00 academy time on the due date"),
        ],
      },
      {
        key: "late_payments",
        title: "Late payments",
        note: "Applied automatically. Every hour, each open invoice whose grace period has ended gets the late fee once.",
        rows: [
          editable("grace_days", 3, "days", 0, 60, "Grace days after due"),
          editable("late_fee_cents", 2500, "cents", 0, 100000, "Late fee"),
        ],
      },
    ],
  };
}

test("editable and fixed rows are separated by the backend's flag", () => {
  assert.deepEqual(
    editableRows(view()).map((row) => row.key),
    ["billing_day", "invoice_due_days", "grace_days", "late_fee_cents"],
  );
  assert.equal(editableRows(null).length, 0);
});

test("cents rows round-trip through dollars", () => {
  const row = editable("late_fee_cents", 2500, "cents", 0, 100000);
  assert.equal(rowToInput(row), "25.00");
  assert.equal(inputToValue(row, "25.00", MONEY), 2500);
  assert.equal(inputToValue(row, "25", MONEY), 2500);
  assert.equal(inputToValue(row, " 0.05 ", MONEY), 5);
});

test("a whole-number row never accepts a fractional value", () => {
  const row = editable("billing_day", 1, "day_of_month", 1, 28);
  assert.equal(rowToInput(row), "1");
  assert.equal(inputToValue(row, "12", MONEY), 12);
  assert.equal(inputToValue(row, "12.5", MONEY), null);
  assert.equal(inputToValue(row, "abc", MONEY), null);
});

test("an unset fee shows an empty box, not a zero", () => {
  assert.equal(rowToInput(editable("late_fee_cents", null, "cents", 0, 100000)), "");
  assert.equal(toForm(view()).late_fee_cents, "25.00");
});

test("the diff carries only the changed fields", () => {
  const form = { ...toForm(view()), late_fee_cents: "30.00" };
  const diff = diffForm(view(), form, MONEY);
  assert.deepEqual(diff.changed, ["late_fee_cents"]);
  assert.deepEqual(diff.payload, { late_fee_cents: 3000 });
  assert.equal(canSave(diff), true);
});

test("an unchanged form saves nothing", () => {
  const diff = diffForm(view(), toForm(view()), MONEY);
  assert.deepEqual(diff.changed, []);
  assert.equal(canSave(diff), false);
  assert.equal(saveSummary(diff), "No changes");
});

test("the save button says which fields it will write", () => {
  const diff = diffForm(view(), {
    ...toForm(view()),
    late_fee_cents: "30.00",
    grace_days: "5",
  }, MONEY);
  assert.equal(saveSummary(diff), "Save Grace days after due and Late fee");
});

test("a value outside its bound is an error, not a payload field", () => {
  const diff = diffForm(view(), { ...toForm(view()), billing_day: "31" }, MONEY);
  assert.deepEqual(diff.changed, []);
  assert.equal(canSave(diff), false);
  assert.equal(diff.errors.billing_day, "Enter a whole number between 1 and 28.");
});

test("a junk entry is an error, not a silent zero", () => {
  const diff = diffForm(view(), { ...toForm(view()), late_fee_cents: "12 34" }, MONEY);
  assert.deepEqual(diff.payload, {});
  assert.match(diff.errors.late_fee_cents, /^Enter an amount between \$0\.00 and \$1,000\.00\.$/);
});

test("a blank box means leave it alone, never clear it", () => {
  const diff = diffForm(view(), { ...toForm(view()), grace_days: "" }, MONEY);
  assert.deepEqual(diff.changed, []);
  assert.deepEqual(diff.errors, {});
});

test("money bounds are stated in dollars, day bounds as whole numbers", () => {
  assert.equal(
    boundsMessage(editable("late_fee_cents", 0, "cents", 0, 100000), MONEY),
    "Enter an amount between $0.00 and $1,000.00.",
  );
  assert.equal(
    boundsMessage(editable("grace_days", 0, "days", 0, 60), MONEY),
    "Enter a whole number between 0 and 60.",
  );
});

test("fixed rows are rendered without an input element", () => {
  const fixedBlock = panel.slice(panel.indexOf("function FixedRule"));
  assert.equal(fixedBlock.includes("<input"), false);
});

test("the late-payments note renders above the rows, not below", () => {
  const card = panel.slice(panel.indexOf("function RuleGroupCard"), panel.indexOf("function EditableRule"));
  assert.ok(card.indexOf("group.note") < card.indexOf("row.editable"));
});

test("?panel=fees still lands on Billing rules", () => {
  assert.match(tabs, /fees: "billing-rules"/);
  assert.match(settingsPage, /RETIRED_SETTINGS_PANELS\[value\]/);
});

test("the Billing rules tab stays owner-only", () => {
  const ownerOnly = tabs.slice(tabs.indexOf("OWNER_ONLY_SETTINGS_PANELS"));
  assert.match(ownerOnly, /"billing-rules"/);
});

test("the retired panels are gone from the settings page", () => {
  assert.equal(settingsPage.includes("FeesPanel"), false);
  assert.equal(settingsPage.includes("InvoiceSchedulePanel"), false);
});

// --- reminder_days: the one list-valued rule (issue #774) -------------------

function reminderRow(values) {
  return {
    key: "reminder_days",
    label: "Past-due reminder days",
    editable: true,
    value: null,
    values,
    unit: "days",
    min_value: 1,
    max_value: 60,
    display: null,
    detail: null,
  };
}

function reminderView(values) {
  return { groups: [{ key: "parent_messages", title: "Parent messages", note: null, rows: [reminderRow(values)] }] };
}

test("reminder_days round-trips as a comma-separated list", () => {
  assert.equal(rowToInput(reminderRow([15, 20])), "15, 20");
  assert.deepEqual(toForm(reminderView([15, 20])), { reminder_days: "15, 20" });
});

test("editing reminder_days sends the parsed, sorted day offsets", () => {
  const diff = diffForm(reminderView([15, 20]), { reminder_days: "20, 10" }, MONEY);
  assert.deepEqual(diff.payload, { reminder_days: [10, 20] });
  assert.deepEqual(diff.changed, ["reminder_days"]);
  assert.equal(canSave(diff), true);
});

test("a blank reminder_days box turns reminders OFF rather than meaning 'leave alone'", () => {
  const diff = diffForm(reminderView([15, 20]), { reminder_days: "" }, MONEY);
  assert.deepEqual(diff.payload, { reminder_days: [] });
  assert.equal(canSave(diff), true);
});

test("reminder_days already off stays a no-op", () => {
  const diff = diffForm(reminderView([]), { reminder_days: "" }, MONEY);
  assert.deepEqual(diff.changed, []);
  assert.equal(canSave(diff), false);
});

test("out-of-range and non-numeric reminder days are refused inline", () => {
  const tooBig = diffForm(reminderView([15]), { reminder_days: "15, 90" }, MONEY);
  assert.ok(tooBig.errors.reminder_days);
  assert.deepEqual(tooBig.payload, {});

  const junk = diffForm(reminderView([15]), { reminder_days: "15, soon" }, MONEY);
  assert.ok(junk.errors.reminder_days);
  assert.deepEqual(junk.payload, {});
});

// --- Money audit 2026-09-25 ---------------------------------------------------

function viewWith(key, value) {
  const v = view();
  for (const group of v.groups) {
    group.rows = group.rows.map((row) => (row.key === key ? { ...row, value } : row));
  }
  return v;
}

test("an out-of-bounds value already stored does not lock the other fields (X16)", () => {
  // The Self-service tab and the legacy fees route allowed values Billing rules
  // does not. The untouched row used to fail validation and disable Save.
  const stored = viewWith("late_fee_cents", 250000);
  const diff = diffForm(stored, { ...toForm(stored), grace_days: "5" }, MONEY);
  assert.deepEqual(diff.errors, {});
  assert.deepEqual(diff.payload, { grace_days: 5 });
  assert.equal(canSave(diff), true);
});

test("editing an out-of-bounds value still has to land inside the bounds", () => {
  const stored = viewWith("late_fee_cents", 250000);
  const diff = diffForm(stored, { ...toForm(stored), late_fee_cents: "2000.00" }, MONEY);
  assert.ok(diff.errors.late_fee_cents);
  assert.equal(canSave(diff), false);
});

test("turning a late fee on from unset or $0 is detected (X4 warning)", () => {
  for (const before of [null, 0]) {
    const stored = viewWith("late_fee_cents", before);
    const diff = diffForm(stored, { ...toForm(stored), late_fee_cents: "15.00" }, MONEY);
    assert.equal(turnsLateFeeOn(stored, diff), true);
  }
});

test("changing a fee that is already on, or turning it off, is not a turn-on", () => {
  const raised = diffForm(view(), { ...toForm(view()), late_fee_cents: "30.00" }, MONEY);
  assert.equal(turnsLateFeeOn(view(), raised), false);
  const off = diffForm(view(), { ...toForm(view()), late_fee_cents: "0" }, MONEY);
  assert.equal(turnsLateFeeOn(view(), off), false);
  const untouched = diffForm(view(), { ...toForm(view()), grace_days: "9" }, MONEY);
  assert.equal(turnsLateFeeOn(view(), untouched), false);
});

test("turning a fee on needs an explicit acknowledgement before Save is enabled", () => {
  assert.match(panel, /billing-rules-late-fee-warning/);
  assert.match(panel, /turnsLateFeeOn\(/);
  assert.match(panel, /lateFeeAcknowledged/);
});
