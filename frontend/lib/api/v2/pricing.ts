/**
 * Pricing page client (Settings overhaul Phase 3 PR 11b).
 *
 * Owner only: every route 403s for an admin without the owner scope, except
 * `GET /admin/pricing/scheduled-class-fees` (the class editor's "Scheduled"
 * note), which any admin can read.
 * Backed by `backend/v2/interfaces/admin/pricing_routes.py`. The plan list
 * itself is edited through `session-types.ts` (plans are session types).
 */
import { apiFetch } from "../client";

export type PlanType = "monthly" | "per_session";

export interface PricingPlan {
  plan_id: string;
  name: string;
  description: string | null;
  price_cents: number;
  plan_type: PlanType;
  is_active: boolean;
  linked_classes: number;
  updated_at: string;
  /** A scheduled price change for this plan (Settings overhaul PR 26). */
  scheduled_change_id?: string | null;
  scheduled_cents?: number | null;
  /** `YYYY-MM`: the first month charged `scheduled_cents`. */
  scheduled_from?: string | null;
}

export interface PricingClass {
  session_id: string;
  title: string;
  /** What the class is charged per month: its own fee. Links never change it. */
  charged_cents: number;
  /** False when the class has no fee stored (it is billed at 0). */
  fee_set: boolean;
  students: number;
  /** Linked plan, or null for "Custom". */
  plan_id: string | null;
  /** Active plans at exactly this fee: the only plans the class may use. */
  matching_plan_ids: string[];
  /** A stored link whose plan price no longer matches the fee. */
  stale_link: boolean;
  /** Why the stored link is stale. */
  stale_reason?: "archived" | "price_changed" | "plan_removed" | null;
  /** "Scheduled: $X from <Month>": a plan price change will move this fee. */
  scheduled_cents?: number | null;
  scheduled_from?: string | null;
}

export interface PricingSavedOverride {
  source: "billing_plan" | "class_enrollment";
  enrollment_id: string;
  student_id: string | null;
  student_name: string | null;
  label: string | null;
  override_cents: number;
  charged_cents: number | null;
  status: string | null;
}

export interface PricingOverview {
  plans: PricingPlan[];
  classes: PricingClass[];
  saved_overrides: PricingSavedOverride[];
  auto_linkable: number;
}

export interface LinkMatchingClassesResult {
  linked: number;
  no_match: number;
  several_matches: number;
  already_decided: number;
}

export function getPricingOverview(): Promise<PricingOverview> {
  return apiFetch<PricingOverview>("/admin/pricing");
}

/** Link a class to a plan at its own fee, or pass null to mark it custom. */
export function setClassPlan(sessionId: string, planId: string | null): Promise<PricingClass> {
  return apiFetch<PricingClass>(`/admin/pricing/classes/${encodeURIComponent(sessionId)}/plan`, {
    method: "PUT",
    body: JSON.stringify({ plan_id: planId }),
  });
}

export function linkMatchingClasses(): Promise<LinkMatchingClassesResult> {
  return apiFetch<LinkMatchingClassesResult>("/admin/pricing/link-matching-classes", {
    method: "POST",
  });
}

// ------------------------------------------ change a plan price (PR 26)

export interface PriceChangeClassRow {
  session_id: string;
  title: string;
  /** Students the monthly invoice run bills on this class. */
  students: number;
  old_cents: number;
  new_cents: number;
}

export interface PriceChangeUnaffectedRow {
  session_id: string;
  title: string;
  charged_cents: number;
  students: number;
}

export interface PlanPriceChangePreview {
  plan_id: string;
  plan_name: string;
  old_cents: number;
  new_cents: number;
  /** `YYYY-MM`. */
  effective_period: string;
  /** The first month the owner may pick (`YYYY-MM`). */
  earliest_period: string;
  classes: PriceChangeClassRow[];
  /** Custom-price classes at the plan's price: not affected. */
  not_affected: PriceChangeUnaffectedRow[];
  total_classes: number;
  total_students: number;
  old_monthly_cents: number;
  new_monthly_cents: number;
}

export interface PlanPriceChange {
  change_id: string;
  plan_id: string;
  plan_name: string | null;
  old_cents: number;
  new_cents: number;
  effective_period: string;
  session_ids: string[];
  status: "scheduled" | "applied" | "cancelled";
  created_by: string;
  created_at: string | null;
}

export interface ScheduledClassFee {
  session_id: string;
  change_id: string;
  plan_id: string;
  new_cents: number;
  effective_period: string;
}

/** Read only. Omit `effectivePeriod` to get the earliest allowed month. */
export function previewPlanPriceChange(params: {
  planId: string;
  newPriceCents: number;
  effectivePeriod?: string | null;
}): Promise<PlanPriceChangePreview> {
  const query = new URLSearchParams({
    plan_id: params.planId,
    new_price_cents: String(params.newPriceCents),
  });
  if (params.effectivePeriod) query.set("effective_period", params.effectivePeriod);
  return apiFetch<PlanPriceChangePreview>(`/admin/pricing/price-changes/preview?${query}`);
}

export function schedulePlanPriceChange(body: {
  plan_id: string;
  new_price_cents: number;
  effective_period: string;
}): Promise<PlanPriceChange> {
  return apiFetch<PlanPriceChange>("/admin/pricing/price-changes", {
    method: "POST",
    body: JSON.stringify(body),
  });
}

export function cancelPlanPriceChange(changeId: string): Promise<void> {
  return apiFetch<void>(`/admin/pricing/price-changes/${encodeURIComponent(changeId)}`, {
    method: "DELETE",
  });
}

/** Admin-readable: classes whose fee a scheduled change will move. */
export function listScheduledClassFees(): Promise<ScheduledClassFee[]> {
  return apiFetch<ScheduledClassFee[]>("/admin/pricing/scheduled-class-fees");
}

const MONTH_NAMES = [
  "January",
  "February",
  "March",
  "April",
  "May",
  "June",
  "July",
  "August",
  "September",
  "October",
  "November",
  "December",
];

/** "2026-11" -> "November"; with `{ year: true }` -> "November 2026". */
export function formatBillingMonth(period: string, opts?: { year?: boolean }): string {
  const [year, month] = period.split("-").map(Number);
  const name = MONTH_NAMES[(month ?? 1) - 1] ?? period;
  return opts?.year ? `${name} ${year}` : name;
}

/** The `count` months starting at `first` ("2026-11", 3 -> Nov, Dec, Jan). */
export function billingMonthsFrom(first: string, count: number): string[] {
  const [year, month] = first.split("-").map(Number);
  const out: string[] = [];
  for (let i = 0; i < count; i += 1) {
    const index = (month - 1 + i) % 12;
    const y = year + Math.floor((month - 1 + i) / 12);
    out.push(`${y}-${String(index + 1).padStart(2, "0")}`);
  }
  return out;
}

/** "Monthly · 4 classes, 5th free": today's rule for every monthly plan. */
export const PLAN_TYPE_LABEL: Record<PlanType, string> = {
  monthly: "Monthly · 4 classes, 5th free",
  per_session: "Per session",
};
