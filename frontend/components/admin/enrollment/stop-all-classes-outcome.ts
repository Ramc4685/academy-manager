/**
 * Pure outcome-selection logic for the stop-all-classes dialog (issue #698),
 * split out of the component so it can be unit-tested without a DOM/JSX
 * runtime — mirrors the `level-up-review.ts` split in ../admissions.
 */
import type { DropDefaultOutcome } from "@/lib/api/v2/departure-policy";

export type MoneyOutcome = "credit" | "refund" | "adjustment";

/** Mirrors the design contract §1.2 mapping — the dialog pre-selects the
 * academy's configured default, translated into the money-side outcome. */
export function defaultOutcomeFor(policyDefault: DropDefaultOutcome | undefined): MoneyOutcome {
  switch (policyDefault) {
    case "credit_mid_month":
      return "credit";
    case "no_credit_mid_month":
    case "no_credit_end_of_period":
    default:
      return "adjustment";
  }
}

/** Owner gate (design contract §1.2): only "adjustment" (no credit) is open
 * to non-owner roles — issuing a credit or a refund from stop-all-classes
 * requires the owner surface, same as the single-enrollment drop flow. */
export function isMoneyOutcomeAllowed(outcome: MoneyOutcome, isOwner: boolean): boolean {
  if (outcome === "adjustment") return true;
  return isOwner;
}
