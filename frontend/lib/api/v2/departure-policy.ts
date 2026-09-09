/**
 * EnrollmentDeparturePolicy client (issue #697).
 *
 * Sibling of the parent self-service policy (`admin.ts`'s
 * `getSelfServicePolicy`/`updateSelfServicePolicy`) — a separate endpoint on
 * purpose, see `backend/v2/contexts/enrollment/domain/departure_policy.py`.
 * The PUT is owner-only; a plain admin's `updateDeparturePolicy` call 404s.
 */
import { apiFetch } from "../client";

export type HoldReclaimPolicy = "longest_held" | "never";

export type DropDefaultOutcome =
  | "no_credit_mid_month"
  | "credit_mid_month"
  | "no_credit_end_of_period";

export interface EnrollmentDeparturePolicyView {
  max_hold_days: number;
  hold_reclaim_policy: HoldReclaimPolicy;
  drop_default_outcome: DropDefaultOutcome;
  delete_enrollment_requires_owner: boolean;
}

export type UpdateEnrollmentDeparturePolicyRequest = EnrollmentDeparturePolicyView;

export function getDeparturePolicy(): Promise<EnrollmentDeparturePolicyView> {
  return apiFetch<EnrollmentDeparturePolicyView>("/admin/enrollment/departure-policy", {
    method: "GET",
  });
}

export function updateDeparturePolicy(
  payload: UpdateEnrollmentDeparturePolicyRequest,
): Promise<EnrollmentDeparturePolicyView> {
  return apiFetch<EnrollmentDeparturePolicyView>("/admin/enrollment/departure-policy", {
    method: "PUT",
    body: JSON.stringify(payload),
  });
}

export interface HoldEnrollmentRequest {
  return_on: string;
  reason?: string | null;
}

export interface ReturnFromHoldRequest {
  reason?: string | null;
}

export function holdEnrollment(
  enrollmentId: string,
  payload: HoldEnrollmentRequest,
): Promise<void> {
  return apiFetch<void>(`/admin/enrollments/${enrollmentId}/hold`, {
    method: "POST",
    body: JSON.stringify(payload),
  });
}

export function returnFromHold(
  enrollmentId: string,
  payload: ReturnFromHoldRequest = {},
): Promise<void> {
  return apiFetch<void>(`/admin/enrollments/${enrollmentId}/return`, {
    method: "POST",
    body: JSON.stringify(payload),
  });
}
