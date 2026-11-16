"use client";

import { useQuery } from "@tanstack/react-query";

import { Chip } from "@/components/ds";
import {
  fetchFamilySiblingDiscount,
  type FamilySiblingDiscount,
  type SiblingDiscountEnrollment,
} from "@/lib/api/admin-families";
import { queryKeys } from "@/lib/query/keys";

function percentText(bps: number | null): string {
  return bps == null ? "" : `${Number((bps / 100).toFixed(2))}%`;
}

/** `2026-12` -> `December`; the raw label when it is not a period. */
export function periodMonthName(period: string): string {
  const match = /^(\d{4})-(\d{2})$/.exec(period);
  if (!match) return period;
  return new Date(Date.UTC(Number(match[1]), Number(match[2]) - 1, 1)).toLocaleString("en-US", {
    month: "long",
    timeZone: "UTC",
  });
}

/** Two or more children with an active or paused class on the family. */
export function isSiblingFamily(view: FamilySiblingDiscount): boolean {
  return new Set(view.enrollments.map((r) => r.student_id)).size >= 2;
}

/** Why the monthly run leaves this class off the invoices, in plain words. */
function exclusionText(row: SiblingDiscountEnrollment): string {
  switch (row.exclusion) {
    case "billing_type": {
      // The only non-monthly types on record are the importer's NoCharge and Waived.
      const type = (row.billing_type ?? "").toLowerCase().replace(/[_\s-]/g, "");
      if (type === "nocharge") return "marked No charge";
      if (type === "waived") return "tuition waived";
      return row.billing_type ? `billing type ${row.billing_type}` : "billed outside the monthly run";
    }
    case "paused":
      return "paused this month";
    case "not_active":
      return "not active";
    case "deferral":
      return "billing deferred this month";
    case "pending_cancellation":
      return "cancels before this month";
    case "skip_period":
      return "skipped this month";
    case "no_class_fee":
      return "the class has no monthly fee";
    default:
      return "left off this month's run";
  }
}

/** The label for a class the backend decided on, or `null`. */
function decidedLabel(row: SiblingDiscountEnrollment): string | null {
  if (row.status === "discounted") return `Sibling discount ${percentText(row.percent_bps)} (automatic)`;
  if (row.status === "full_price") return "Pays full price (sibling discount)";
  if (row.reason === "manual_discount_larger") {
    return `Manual discount kept (larger than sibling ${percentText(row.percent_bps)})`;
  }
  return null;
}

/**
 * The badge text for one class, or `null` for no badge. The backend decides
 * (the same decision the monthly invoice run makes); this only words it.
 * With the family's `view`, a switched-on sibling family never goes silent:
 * a month already invoiced says what happens next month, and a class off the
 * monthly invoices says why.
 */
export function siblingBadgeLabel(
  row: SiblingDiscountEnrollment | undefined,
  view?: FamilySiblingDiscount,
): string | null {
  if (!row) return null;
  const decided = decidedLabel(row);
  if (decided) return decided;
  if (!view?.enabled || row.status === "off" || !isSiblingFamily(view)) return null;
  switch (row.reason) {
    case "not_billed_this_month":
      return `Not on monthly invoices: ${exclusionText(row)}, so no sibling discount`;
    case "already_invoiced": {
      const next = view.next_period;
      const ahead = next?.enrollments.find((r) => r.enrollment_id === row.enrollment_id);
      const label = ahead ? decidedLabel(ahead) : null;
      if (next && label) {
        return `From ${periodMonthName(next.period)}: ${label.charAt(0).toLowerCase()}${label.slice(1)}`;
      }
      return `${periodMonthName(view.period)} already invoiced without the sibling discount`;
    }
    case "only_one_child":
      return "No sibling discount: the only child on monthly invoices";
    case "one_class_per_child":
      return "No sibling discount on this class (one class per child)";
    default:
      return null;
  }
}

/**
 * The family's sibling picture, or `undefined` while loading or on error. Not
 * gated on `enabled`: a month billed before the setting went off keeps its badge.
 */
export function useFamilySiblingDiscount(
  parentId: string | null | undefined,
): FamilySiblingDiscount | undefined {
  const query = useQuery({
    queryKey: queryKeys.admin.familySiblingDiscount(parentId ?? ""),
    queryFn: () => fetchFamilySiblingDiscount(parentId ?? ""),
    enabled: Boolean(parentId),
    retry: false,
  });
  return query.data ?? undefined;
}

export function SiblingDiscountChip({
  row,
  view,
}: {
  row: SiblingDiscountEnrollment | undefined;
  view?: FamilySiblingDiscount;
}) {
  const label = siblingBadgeLabel(row, view);
  if (!label || !row) return null;
  return (
    <span data-testid={`sibling-discount-badge-${row.enrollment_id}`}>
      <Chip variant={row.status === "discounted" ? "approved" : "manual"} label={label} />
    </span>
  );
}

function namesWith(
  rows: SiblingDiscountEnrollment[],
  status: SiblingDiscountEnrollment["status"],
  nameOf: (studentId: string) => string,
): string[] {
  return [...new Set(rows.filter((r) => r.status === status).map((r) => nameOf(r.student_id)))];
}

/** The discounted children's percentage: one value, or `null` when mixed. */
function discountedPercent(rows: SiblingDiscountEnrollment[]): string | null {
  const percents = new Set(rows.filter((r) => r.status === "discounted").map((r) => r.percent_bps));
  return percents.size === 1 ? percentText([...percents][0]) : null;
}

/**
 * The family billing page's sibling line: who pays full price and who is
 * discounted this month. A switched-on sibling family always gets a line: a
 * month invoiced before the setting says what happens next month, and a child
 * off the monthly invoices is named with the reason. `null` otherwise.
 */
export function siblingFamilySummary(
  view: FamilySiblingDiscount,
  nameOf: (studentId: string) => string,
): string | null {
  const sentences: string[] = [];
  const full = namesWith(view.enrollments, "full_price", nameOf);
  const discounted = namesWith(view.enrollments, "discounted", nameOf);
  if (full.length || discounted.length) {
    const parts: string[] = [];
    if (full.length) parts.push(`${full.join(", ")} pays full price`);
    if (discounted.length) {
      // The decided (frozen) percentage, not today's setting; mixed only after a mid-month change.
      const percent = discountedPercent(view.enrollments);
      const what = percent ? `${percent} off` : "the sibling discount";
      parts.push(`${discounted.join(", ")} ${discounted.length === 1 ? "gets" : "get"} ${what}`);
    }
    sentences.push(`Sibling discount this month: ${parts.join("; ")}.`);
  }
  if (!view.enabled || !isSiblingFamily(view)) return sentences[0] ?? null;

  if (sentences.length === 0) {
    if (view.enrollments.some((r) => r.reason === "already_invoiced")) {
      sentences.push(`${periodMonthName(view.period)} was already invoiced without the sibling discount.`);
    }
    const next = view.next_period;
    if (next) {
      const nextFull = namesWith(next.enrollments, "full_price", nameOf);
      const nextDiscounted = namesWith(next.enrollments, "discounted", nameOf);
      const percent = discountedPercent(next.enrollments);
      const parts = [
        ...nextFull.map((name) => `${name} pays full price`),
        ...nextDiscounted.map((name) => `${name} ${percent ? `${percent} off` : "gets the sibling discount"}`),
      ];
      if (parts.length) sentences.push(`From ${periodMonthName(next.period)}: ${parts.join(" · ")}.`);
    }
  }
  // A child already named above (one class discounted, another excluded) is not
  // repeated: "Ben: no sibling discount" would contradict "Ben gets 10% off".
  const named = new Set([...full, ...discounted]);
  const excluded = new Set(
    view.enrollments
      .filter((r) => r.reason === "not_billed_this_month" && !named.has(nameOf(r.student_id)))
      .map((r) => `${nameOf(r.student_id)}: not on monthly invoices (${exclusionText(r)}), so no sibling discount.`),
  );
  sentences.push(...excluded);
  if (sentences.length === 0) sentences.push("Sibling discount is on, but no child qualifies this month.");
  return sentences.join(" ");
}
