/**
 * View model for Settings → Billing rules.
 *
 * Spec: `docs/superpowers/specs/2026-09-07-billing-rules-design.md`.
 *
 * Kept free of React so the round-tripping and the changed-field diff the save
 * button reports can be tested directly (`billing-rules-form.node-test.mjs`).
 * The backend decides which rows are editable and what their bounds are; this
 * module only converts between those rows and the form's strings.
 */

/**
 * Money formatting and parsing are injected rather than imported so this
 * module stays dependency-free and Node's test runner can load it directly
 * (`lib/**\/*.node-test.mjs` runs without the `@` path alias). The panel
 * passes `formatCents`/`parseDollarsToCents` from `lib/money`, which stay the
 * one money formatter and the one money parser.
 */
export interface MoneyCodec {
  format: (cents: number) => string;
  /** Dollars string -> cents, or a negative number for anything invalid. */
  parse: (value: string) => number;
}

export type BillingRuleUnit = "day_of_month" | "days" | "cents";

export interface BillingRuleRow {
  key: string;
  label: string;
  editable: boolean;
  value: number | null;
  /**
   * Issue #774: `reminder_days` is the one editable rule that is a LIST — the
   * days after the due date a past-due reminder goes out. `null` on every
   * other row; an EMPTY array means "send none", which is the off switch.
   */
  values?: number[] | null;
  unit: BillingRuleUnit | null;
  min_value: number | null;
  max_value: number | null;
  display: string | null;
  detail: string | null;
  /** `cancellation_effective_timing` only: the stored choice and its options. */
  choice?: string | null;
  choices?: string[] | null;
  /** `ach_discount` only: on/off, the stored percent and its platform ceiling. */
  enabled?: boolean | null;
  percent?: number | null;
  max_percent?: number | null;
}

export interface BillingRuleGroup {
  key: string;
  title: string;
  note: string | null;
  rows: BillingRuleRow[];
}

export interface BillingRulesView {
  groups: BillingRuleGroup[];
}

export type BillingRulesForm = Record<string, string>;

export interface AchDiscountChange {
  enabled?: boolean;
  percent?: number;
}

export type UpdateBillingRulesRequest = Record<
  string,
  number | number[] | string | AchDiscountChange | null
>;

/** The Bank (ACH) discount row (Settings overhaul Phase 4 PR 13). */
export const ACH_KEY = "ach_discount";
/** Form-field names for its two inputs (the form is a flat string map). */
export const ACH_ENABLED_FIELD = "ach_discount_enabled";
export const ACH_PERCENT_FIELD = "ach_discount_percent";

export function isAchRow(row: BillingRuleRow): boolean {
  return row.key === ACH_KEY;
}

const ACH_PERCENT_PATTERN = /^\d+(\.\d{1,2})?$/;

/** "2", "2.5" -> number; anything else (blank, "abc", "2.555") -> null. */
export function achPercentFromInput(raw: string): number | null {
  const trimmed = raw.trim();
  return ACH_PERCENT_PATTERN.test(trimmed) ? Number(trimmed) : null;
}

export function achBoundsMessage(row: BillingRuleRow): string {
  const max = row.max_percent ?? 0;
  return `Enter a percent above 0 and up to ${max}, with at most two decimals.`;
}

export function editableRows(view: BillingRulesView | null | undefined): BillingRuleRow[] {
  return (view?.groups ?? []).flatMap((group) => group.rows.filter((row) => row.editable));
}

/** True for the one rule whose value is a list of day offsets (#774). */
export function isListRow(row: BillingRuleRow): boolean {
  return Array.isArray(row.values);
}

/** True for `cancellation_effective_timing`: a `<select>`, not a number box. */
export function isChoiceRow(row: BillingRuleRow): boolean {
  return Array.isArray(row.choices);
}

/** Stored value → the string the input shows. Cents rows show dollars. */
export function rowToInput(row: BillingRuleRow): string {
  if (isListRow(row)) return (row.values ?? []).join(", ");
  if (isChoiceRow(row)) return row.choice ?? "";
  if (row.value === null || row.value === undefined) return "";
  return row.unit === "cents" ? (row.value / 100).toFixed(2) : String(row.value);
}

/**
 * "15, 20" → [15, 20]; blank → [] (the off switch). `null` for anything that
 * is not a list of whole numbers, so the panel can say so inline.
 */
export function inputToDays(raw: string): number[] | null {
  const trimmed = raw.trim();
  if (trimmed === "") return [];
  const parts = trimmed.split(/[,\s]+/).filter(Boolean);
  const days: number[] = [];
  for (const part of parts) {
    if (!/^\d+$/.test(part)) return null;
    const day = Number(part);
    if (!days.includes(day)) days.push(day);
  }
  return days.sort((a, b) => a - b);
}

function sameDays(a: number[], b: number[]): boolean {
  return a.length === b.length && a.every((day, i) => day === b[i]);
}

export function toForm(view: BillingRulesView | null | undefined): BillingRulesForm {
  const form: BillingRulesForm = {};
  for (const row of editableRows(view)) {
    if (isAchRow(row)) {
      form[ACH_ENABLED_FIELD] = row.enabled ? "true" : "false";
      form[ACH_PERCENT_FIELD] = row.percent ? String(row.percent) : "";
      continue;
    }
    form[row.key] = rowToInput(row);
  }
  return form;
}

/**
 * Diff the ACH row: on/off plus a percent. Only the parts that changed are
 * sent; the server fills the rest from what is stored and enforces the
 * platform ceiling. Untouched is never an error (money audit X16).
 */
function diffAchRow(
  row: BillingRuleRow,
  form: BillingRulesForm,
  out: { changed: string[]; changedLabels: string[]; payload: UpdateBillingRulesRequest; errors: Record<string, string> },
): void {
  const storedEnabled = Boolean(row.enabled);
  const storedPercent = row.percent ?? 0;
  const enabled = (form[ACH_ENABLED_FIELD] ?? String(storedEnabled)) === "true";
  const rawPercent = (form[ACH_PERCENT_FIELD] ?? "").trim();
  const parsed = rawPercent === "" ? null : achPercentFromInput(rawPercent);

  const enabledChanged = enabled !== storedEnabled;
  const percentEdited = rawPercent !== "" && !(parsed !== null && parsed === storedPercent);
  if (!enabledChanged && !percentEdited) return;

  const max = row.max_percent ?? Number.POSITIVE_INFINITY;
  const effective = percentEdited ? parsed : storedPercent;
  const invalid =
    (percentEdited && (parsed === null || parsed <= 0 || parsed > max)) ||
    (enabled && (effective === null || effective <= 0 || effective > max));
  if (invalid) {
    out.errors[row.key] = achBoundsMessage(row);
    return;
  }
  const change: AchDiscountChange = {};
  if (enabledChanged) change.enabled = enabled;
  if (percentEdited && parsed !== null) change.percent = parsed;
  out.changed.push(row.key);
  out.changedLabels.push(row.label);
  out.payload[row.key] = change;
}

/** The input's string → cents/whole number, or null when it is not a number. */
export function inputToValue(row: BillingRuleRow, raw: string, money: MoneyCodec): number | null {
  const trimmed = raw.trim();
  if (trimmed === "") return null;
  if (row.unit === "cents") {
    const cents = money.parse(trimmed);
    return cents < 0 ? null : cents;
  }
  if (!/^-?\d+$/.test(trimmed)) return null;
  return Number(trimmed);
}

export function boundsMessage(row: BillingRuleRow, money: MoneyCodec): string {
  const low = row.min_value ?? 0;
  const high = row.max_value ?? 0;
  if (isListRow(row)) {
    return `Enter whole numbers between ${low} and ${high}, separated by commas. Leave empty to send none.`;
  }
  if (row.unit === "cents") {
    return `Enter an amount between ${money.format(low)} and ${money.format(high)}.`;
  }
  return `Enter a whole number between ${low} and ${high}.`;
}

export interface BillingRulesDiff {
  /** Keys whose input differs from the stored value and is valid. */
  changed: string[];
  /** The PUT body: only the changed fields. */
  payload: UpdateBillingRulesRequest;
  /** Per-field message, rendered inline against the offending input. */
  errors: Record<string, string>;
  /** Labels of the fields the save button says it will write. */
  changedLabels: string[];
}

/**
 * Diff the form against the loaded view.
 *
 * A blank input means "leave this alone" — the fee fields can legitimately be
 * unset, and clearing one is not a supported edit, so an empty box is never
 * sent and never an error.
 */
export function diffForm(
  view: BillingRulesView | null | undefined,
  form: BillingRulesForm,
  money: MoneyCodec,
): BillingRulesDiff {
  const changed: string[] = [];
  const changedLabels: string[] = [];
  const payload: UpdateBillingRulesRequest = {};
  const errors: Record<string, string> = {};

  for (const row of editableRows(view)) {
    if (isAchRow(row)) {
      diffAchRow(row, form, { changed, changedLabels, payload, errors });
      continue;
    }
    const raw = form[row.key] ?? "";
    if (isListRow(row)) {
      // Blank is a REAL value here, not "leave alone": empty means send no
      // reminders at all, which is how an academy turns them off (#774).
      const days = inputToDays(raw);
      const stored = row.values ?? [];
      // Untouched is never an error, even if the stored list is out of bounds.
      if (days !== null && sameDays(days, stored)) continue;
      if (
        days === null ||
        days.some(
          (day) =>
            (row.min_value !== null && day < row.min_value) ||
            (row.max_value !== null && day > row.max_value),
        )
      ) {
        errors[row.key] = boundsMessage(row, money);
        continue;
      }
      if (!sameDays(days, stored)) {
        changed.push(row.key);
        changedLabels.push(row.label);
        payload[row.key] = days;
      }
      continue;
    }
    if (isChoiceRow(row)) {
      // Untouched or blank is never an edit; the select always shows a
      // stored value so "blank" only happens before the view has loaded.
      if (raw.trim() === "" || raw === (row.choice ?? "")) continue;
      changed.push(row.key);
      changedLabels.push(row.label);
      payload[row.key] = raw;
      continue;
    }
    if (raw.trim() === "") continue;
    const parsed = inputToValue(row, raw, money);
    if (parsed === null) {
      errors[row.key] = boundsMessage(row, money);
      continue;
    }
    // An untouched row is not an edit. Checking its bounds anyway locked the
    // whole page whenever another route had stored a value outside them
    // (money audit X16): every row failed and Save stayed disabled.
    if (parsed === row.value) continue;
    if (
      (row.min_value !== null && parsed < row.min_value) ||
      (row.max_value !== null && parsed > row.max_value)
    ) {
      errors[row.key] = boundsMessage(row, money);
      continue;
    }
    if (parsed !== row.value) {
      changed.push(row.key);
      changedLabels.push(row.label);
      payload[row.key] = parsed;
    }
  }

  return { changed, payload, errors, changedLabels };
}

export function canSave(diff: BillingRulesDiff): boolean {
  return diff.changed.length > 0 && Object.keys(diff.errors).length === 0;
}

/** "Save Late fee and Grace days after due" — says what will be written. */
export function saveSummary(diff: BillingRulesDiff): string {
  if (diff.changedLabels.length === 0) return "No changes";
  if (diff.changedLabels.length === 1) return `Save ${diff.changedLabels[0]}`;
  const head = diff.changedLabels.slice(0, -1).join(", ");
  return `Save ${head} and ${diff.changedLabels[diff.changedLabels.length - 1]}`;
}

/**
 * True when this save switches the late fee on: stored unset or $0, saved as
 * more than $0. The hourly late-fee pass starts charging from that day, so
 * the panel asks the owner to acknowledge what that means before Save is
 * enabled (money audit X4).
 */
export function turnsLateFeeOn(
  view: BillingRulesView | null | undefined,
  diff: BillingRulesDiff,
): boolean {
  const next = diff.payload.late_fee_cents;
  if (typeof next !== "number" || next <= 0) return false;
  const stored = editableRows(view).find((row) => row.key === "late_fee_cents")?.value ?? 0;
  return stored <= 0;
}
