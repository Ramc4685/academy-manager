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

/**
 * The badge text for one class, or `null` for no badge. The backend decides
 * (the same decision the monthly invoice run makes); this only words it.
 */
export function siblingBadgeLabel(row: SiblingDiscountEnrollment | undefined): string | null {
  if (!row) return null;
  if (row.status === "discounted") return `Sibling discount ${percentText(row.percent_bps)} (automatic)`;
  if (row.status === "full_price") return "Pays full price (sibling discount)";
  if (row.reason === "manual_discount_larger") {
    return `Manual discount kept (larger than sibling ${percentText(row.percent_bps)})`;
  }
  return null;
}

/** The family's sibling picture, or `undefined` while loading, off or on error. */
export function useFamilySiblingDiscount(
  parentId: string | null | undefined,
): FamilySiblingDiscount | undefined {
  const query = useQuery({
    queryKey: queryKeys.admin.familySiblingDiscount(parentId ?? ""),
    queryFn: () => fetchFamilySiblingDiscount(parentId ?? ""),
    enabled: Boolean(parentId),
    retry: false,
  });
  return query.data?.enabled ? query.data : undefined;
}

export function SiblingDiscountChip({ row }: { row: SiblingDiscountEnrollment | undefined }) {
  const label = siblingBadgeLabel(row);
  if (!label || !row) return null;
  return (
    <span data-testid={`sibling-discount-badge-${row.enrollment_id}`}>
      <Chip variant={row.status === "discounted" ? "approved" : "manual"} label={label} />
    </span>
  );
}

/**
 * One line for the family billing page: who pays full price and who is
 * discounted this month, or `null` when nobody is either.
 */
export function siblingFamilySummary(
  view: FamilySiblingDiscount,
  nameOf: (studentId: string) => string,
): string | null {
  const names = (status: SiblingDiscountEnrollment["status"]) => [
    ...new Set(view.enrollments.filter((r) => r.status === status).map((r) => nameOf(r.student_id))),
  ];
  const full = names("full_price");
  const discounted = names("discounted");
  if (full.length === 0 && discounted.length === 0) return null;
  const parts: string[] = [];
  if (full.length) parts.push(`${full.join(", ")} pays full price`);
  if (discounted.length) {
    // The decided (frozen) percentage, not today's setting; mixed only after a mid-month change.
    const percents = new Set(
      view.enrollments.filter((r) => r.status === "discounted").map((r) => r.percent_bps),
    );
    const what = percents.size === 1 ? `${percentText([...percents][0])} off` : "the sibling discount";
    parts.push(`${discounted.join(", ")} ${discounted.length === 1 ? "gets" : "get"} ${what}`);
  }
  return `Sibling discount this month: ${parts.join("; ")}.`;
}
