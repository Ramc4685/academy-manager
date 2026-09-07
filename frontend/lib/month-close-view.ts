/**
 * Pure view helpers for the Month close page.
 *
 * Data in, strings out — no DOM, no React — so the tiles, the "Anything odd"
 * rows and the Autopay run box can be tested under plain Node. Shapes and
 * wording follow the month close spec
 * (docs/superpowers/specs/2026-09-07-month-close-design.md §4.3, §5).
 */

import type {
  AdminMonthCloseOdd,
  AdminMonthCloseTally,
  AdminMonthCloseView,
  MonthCloseOddCode,
} from "./api/admin";

/**
 * Nothing here formats money or dates: the page does that with the one
 * `formatCents` / `formatDateOnly` in `lib/money.ts`. Keeping this module free
 * of runtime imports is also what lets it run under plain `node --test`.
 */

/** How many linked items the backend ships per odd check. */
export const ODD_ITEM_LIMIT = 20;

export const ODD_LABELS: Record<MonthCloseOddCode, string> = {
  invoice_without_enrollment: "Invoice without enrollment",
  paused_family_invoiced: "Paused family still invoiced",
  autopay_no_card: "Autopay on with no card on file",
  autopay_on_dead_enrollment: "Autopay on a cancelled or withdrawn enrollment",
};

/** Every check renders, even at zero, so the owner learns the shape of the box. */
export const ODD_ORDER: MonthCloseOddCode[] = [
  "invoice_without_enrollment",
  "paused_family_invoiced",
  "autopay_no_card",
  "autopay_on_dead_enrollment",
];

const WARNING_LABELS: Record<string, string> = {
  attempts_unavailable: "charge attempts could not be read",
  dunning_unavailable: "the autopay retry ladder could not be read",
  discounts_unavailable: "the tuition discount summary could not be read",
  card_state_unavailable: "cards on file could not be read, so the autopay-without-a-card check was skipped",
};

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null;
}

function numberOr(value: unknown, fallback: number): number {
  return typeof value === "number" && Number.isFinite(value) ? value : fallback;
}

function stringOr(value: unknown, fallback: string): string {
  return typeof value === "string" ? value : fallback;
}

function tally(value: unknown): AdminMonthCloseTally {
  const raw = isRecord(value) ? value : {};
  return { count: numberOr(raw.count, 0), cents: numberOr(raw.cents, 0) };
}

/**
 * Coerce whatever the endpoint (or an e2e stub) returned into a full view.
 * Never throws: a missing section renders as zeros rather than crashing the
 * page, which is the failure mode that took the old Reports page down.
 */
export function normalizeMonthClose(data: unknown, period = ""): AdminMonthCloseView {
  const raw = isRecord(data) ? data : {};
  const invoices = isRecord(raw.invoices) ? raw.invoices : {};
  const money = isRecord(raw.money) ? raw.money : {};
  const run = isRecord(raw.autopay_run) ? raw.autopay_run : {};
  const discounts = isRecord(raw.tuition_discounts) ? raw.tuition_discounts : null;

  const rate = money.collection_rate;
  return {
    generated_at: stringOr(raw.generated_at, ""),
    timezone: stringOr(raw.timezone, ""),
    period: stringOr(raw.period, period),
    invoices: {
      generated: numberOr(invoices.generated, 0),
      emailed: numberOr(invoices.emailed, 0),
      autopay_notices: numberOr(invoices.autopay_notices, 0),
      not_sent: numberOr(invoices.not_sent, 0),
      voided: numberOr(invoices.voided, 0),
      voided_cents: numberOr(invoices.voided_cents, 0),
      void_reasons: Array.isArray(invoices.void_reasons)
        ? invoices.void_reasons
            .filter(isRecord)
            .map((entry) => ({
              reason: stringOr(entry.reason, "unspecified"),
              count: numberOr(entry.count, 0),
            }))
        : [],
    },
    money: {
      billed_cents: numberOr(money.billed_cents, 0),
      collected_cents: numberOr(money.collected_cents, 0),
      outstanding_cents: numberOr(money.outstanding_cents, 0),
      collection_rate: typeof rate === "number" && Number.isFinite(rate) ? rate : null,
    },
    autopay_run: {
      charge_on: typeof run.charge_on === "string" ? run.charge_on : null,
      charge_on_varies: run.charge_on_varies === true,
      has_run: run.has_run === true,
      scheduled: tally(run.scheduled),
      succeeded: tally(run.succeeded),
      failed: tally(run.failed),
      pending: tally(run.pending),
    },
    odd: Array.isArray(raw.odd)
      ? raw.odd.filter(isRecord).map((entry) => ({
          code: stringOr(entry.code, "invoice_without_enrollment") as MonthCloseOddCode,
          label: stringOr(entry.label, ""),
          count: numberOr(entry.count, 0),
          items: Array.isArray(entry.items)
            ? entry.items.filter(isRecord).map((item) => ({
                kind: item.kind === "invoice" ? ("invoice" as const) : ("family" as const),
                id: stringOr(item.id, ""),
                label: stringOr(item.label, ""),
                href: stringOr(item.href, "#"),
              }))
            : [],
        }))
      : [],
    tuition_discounts: discounts
      ? {
          gross_cents: numberOr(discounts.gross_cents, 0),
          discount_cents: numberOr(discounts.discount_cents, 0),
          net_cents: numberOr(discounts.net_cents, 0),
          by_category: Array.isArray(discounts.by_category)
            ? discounts.by_category.filter(isRecord).map((row) => ({
                category: stringOr(row.category, "Uncategorised"),
                amount_cents: numberOr(row.amount_cents, 0),
              }))
            : [],
        }
      : null,
    warnings: Array.isArray(raw.warnings)
      ? raw.warnings.filter((w): w is string => typeof w === "string")
      : [],
  };
}

/**
 * The collection rate as a percentage, or "—" when nothing was billed.
 *
 * Never "0%": an empty month has no rate to report, and showing zero reads as
 * a total collection failure (spec §4.3).
 */
export function formatCollectionRate(rate: number | null | undefined): string {
  if (rate == null || !Number.isFinite(rate)) return "—";
  return `${Math.round(rate * 100)}%`;
}

export interface MonthCloseTile {
  key: string;
  label: string;
  /** A count tile carries `value`; a money tile carries `cents` instead. */
  value?: string;
  cents?: number;
  hint: string;
}

function plural(count: number, one: string, many: string): string {
  return `${count} ${count === 1 ? one : many}`;
}

/** The six header tiles, in the order the wireframe puts them. */
export function monthCloseTiles(view: AdminMonthCloseView): MonthCloseTile[] {
  const { invoices, money } = view;
  return [
    {
      key: "generated",
      label: "Invoices generated",
      value: String(invoices.generated),
      hint: invoices.not_sent > 0 ? `${invoices.not_sent} not sent` : "all sent",
    },
    {
      key: "emailed",
      label: "Emailed",
      // The sum is the true sent count; the split is re-derived from the
      // enrollment's autopay status, so it lives in the hint (spec §4.3).
      value: String(invoices.emailed + invoices.autopay_notices),
      hint: `${invoices.emailed} invoice emails · ${invoices.autopay_notices} autopay notices`,
    },
    {
      key: "voided",
      label: "Voided",
      value: String(invoices.voided),
      hint: invoices.voided > 0 ? "see reasons below" : "nothing voided",
    },
    {
      key: "billed",
      label: "Billed",
      cents: money.billed_cents,
      hint: "tuition and fees invoiced for this month",
    },
    {
      key: "collected",
      label: "Collected",
      cents: money.collected_cents,
      hint: `${formatCollectionRate(money.collection_rate)} of what was billed`,
    },
    {
      key: "outstanding",
      label: "Outstanding",
      cents: money.outstanding_cents,
      hint: "still owed on this month's invoices",
    },
  ];
}

export type MonthCloseRunState = "scheduled" | "ran" | "none";

export interface MonthCloseRunBox {
  /**
   * `scheduled` before the charge date, `ran` on or after it, `none` when the
   * month has no autopay invoice at all.
   */
  state: MonthCloseRunState;
  hasRun: boolean;
  /** Calendar date the worker charges on; the page formats it. */
  chargeOn: string | null;
  /** True when the run's invoices do not share one due date ("and later"). */
  chargeOnVaries: boolean;
  rows: { key: string; label: string; countLabel: string; cents: number }[];
}

/**
 * The Autopay run box.
 *
 * Before the charge date only the scheduled figure means anything, so the box
 * shows what the worker still has to do; on or after it, the outcome tallies.
 */
export function autopayRunBox(view: AdminMonthCloseView): MonthCloseRunBox {
  const run = view.autopay_run;
  const state: MonthCloseRunState = !run.charge_on ? "none" : run.has_run ? "ran" : "scheduled";

  const rows: MonthCloseRunBox["rows"] = [
    {
      key: "scheduled",
      label: "Scheduled",
      countLabel: plural(run.scheduled.count, "charge", "charges"),
      cents: run.scheduled.cents,
    },
  ];
  if (run.has_run) {
    rows.push(
      {
        key: "succeeded",
        label: "Succeeded",
        countLabel: plural(run.succeeded.count, "charge", "charges"),
        cents: run.succeeded.cents,
      },
      {
        key: "failed",
        label: "Failed",
        countLabel: plural(run.failed.count, "charge", "charges"),
        cents: run.failed.cents,
      },
    );
    // Non-zero only when a late-added invoice has not reached its due date.
    if (run.pending.count > 0) {
      rows.push({
        key: "pending",
        label: "Not attempted yet",
        countLabel: plural(run.pending.count, "charge", "charges"),
        cents: run.pending.cents,
      });
    }
  } else {
    rows.push({
      key: "pending",
      label: "Waiting to charge",
      countLabel: plural(run.pending.count, "charge", "charges"),
      cents: run.pending.cents,
    });
  }
  return {
    state,
    hasRun: run.has_run,
    chargeOn: run.charge_on,
    chargeOnVaries: run.charge_on_varies,
    rows,
  };
}

export interface MonthCloseOddRow {
  code: MonthCloseOddCode;
  label: string;
  count: number;
  items: AdminMonthCloseOdd["items"];
  /** "showing 20 of 46" when the backend truncated the item list. */
  truncatedNote: string | null;
  expandable: boolean;
}

/**
 * All four checks in a fixed order, whether or not the backend sent them —
 * a check with count 0 still renders, showing a zero.
 */
export function oddRows(view: AdminMonthCloseView): MonthCloseOddRow[] {
  const byCode = new Map(view.odd.map((entry) => [entry.code, entry]));
  return ODD_ORDER.map((code) => {
    const entry = byCode.get(code);
    const count = entry?.count ?? 0;
    const items = entry?.items ?? [];
    return {
      code,
      label: entry?.label || ODD_LABELS[code],
      count,
      items,
      truncatedNote:
        count > items.length && items.length > 0 ? `showing ${items.length} of ${count}` : null,
      expandable: items.length > 0,
    };
  });
}

/** One muted line naming every source that could not be read, or null. */
export function warningLine(view: AdminMonthCloseView): string | null {
  if (view.warnings.length === 0) return null;
  const parts = view.warnings.map((code) => WARNING_LABELS[code] ?? code.replaceAll("_", " "));
  return `Some numbers are incomplete: ${parts.join("; ")}.`;
}
