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
  unit: BillingRuleUnit | null;
  min_value: number | null;
  max_value: number | null;
  display: string | null;
  detail: string | null;
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

export type UpdateBillingRulesRequest = Record<string, number | string | null>;

export function editableRows(view: BillingRulesView | null | undefined): BillingRuleRow[] {
  return (view?.groups ?? []).flatMap((group) => group.rows.filter((row) => row.editable));
}

/** Stored value → the string the input shows. Cents rows show dollars. */
export function rowToInput(row: BillingRuleRow): string {
  if (row.value === null || row.value === undefined) return "";
  return row.unit === "cents" ? (row.value / 100).toFixed(2) : String(row.value);
}

export function toForm(view: BillingRulesView | null | undefined): BillingRulesForm {
  const form: BillingRulesForm = {};
  for (const row of editableRows(view)) form[row.key] = rowToInput(row);
  return form;
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
    const raw = form[row.key] ?? "";
    if (raw.trim() === "") continue;
    const parsed = inputToValue(row, raw, money);
    if (parsed === null) {
      errors[row.key] = boundsMessage(row, money);
      continue;
    }
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
