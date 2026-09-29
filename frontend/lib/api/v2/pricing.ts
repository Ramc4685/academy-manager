/**
 * Pricing page client (Settings overhaul Phase 3 PR 11b).
 *
 * Owner only: every route 403s for an admin without the owner scope.
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

/** "Monthly · 4 classes, 5th free": today's rule for every monthly plan. */
export const PLAN_TYPE_LABEL: Record<PlanType, string> = {
  monthly: "Monthly · 4 classes, 5th free",
  per_session: "Per session",
};
