import type { BillingSetupRow } from "@/lib/api/admin";

/**
 * Issue #865: narrowing the Families list to the families who owe, and
 * ranking it by what they owe.
 *
 * Client-side on purpose. Every row the page has already carries
 * `outstanding_balance_cents` (`fetchBillingSetup`), so this is a rendering
 * order over data in hand — not a new `status` enum value, which would mean a
 * new backend filter and a new query key for a question the DTO already
 * answers. The trade-off is honest and bounded: it ranks the pages loaded so
 * far, the same rows the admin can see, and "Load more families" extends it.
 */

export type FamilySort = "default" | "outstanding_desc";

export interface FamilyRowView {
  owesOnly?: boolean;
  sort?: FamilySort;
}

/**
 * Money owed is a positive balance. A credit (a negative balance, from an
 * over-payment or a withdrawal credit) is the opposite of a family to chase,
 * so `owesOnly` must not sweep it in with `!== 0`.
 */
function owesMoney(row: BillingSetupRow): boolean {
  return row.outstanding_balance_cents > 0;
}

export function visibleFamilyRows(
  rows: readonly BillingSetupRow[],
  { owesOnly = false, sort = "default" }: FamilyRowView = {},
): BillingSetupRow[] {
  const filtered = owesOnly ? rows.filter(owesMoney) : [...rows];
  if (sort !== "outstanding_desc") return filtered;
  // Decorated sort with the original index as the tie-break: two families who
  // owe the same amount must not trade places between refetches, or the row a
  // thumb is travelling towards moves out from under it.
  return filtered
    .map((row, index) => ({ row, index }))
    .sort(
      (a, b) =>
        b.row.outstanding_balance_cents - a.row.outstanding_balance_cents || a.index - b.index,
    )
    .map((entry) => entry.row);
}
