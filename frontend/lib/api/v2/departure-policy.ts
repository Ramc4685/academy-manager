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

/**
 * Stop all classes (issue #698): one date, one reason, one outcome, applied
 * to every active/held/paused enrollment for the student. `outcome` omitted
 * lets the academy's configured `drop_default_outcome` decide it; `"credit"`
 * (explicit or as the resolved default) is owner-gated per action, same as
 * a single-enrollment Drop.
 */
export interface StopAllClassesRequest {
  effective_date: string;
  outcome?: "credit" | "refund" | "adjustment" | null;
  reason: string;
}

export interface EnrollmentStopResult {
  enrollment_id: string;
  session_id: string;
  outcome: "dropped" | "failed";
  error?: string | null;
}

export interface StopAllClassesResponse {
  student_id: string;
  dropped_count: number;
  failed_count: number;
  results: EnrollmentStopResult[];
}

export function stopAllClasses(
  studentId: string,
  payload: StopAllClassesRequest,
): Promise<StopAllClassesResponse> {
  return apiFetch<StopAllClassesResponse>(`/admin/students/${studentId}/stop-all-classes`, {
    method: "POST",
    body: JSON.stringify(payload),
  });
}

/** The leaving report (issue #698): who left, when, why, and the monthly
 * revenue effect. Owner-only, same tier as every other financial report. */
export interface LeavingReportRow {
  event_id: string;
  student_id: string;
  student_name: string | null;
  enrollment_id: string | null;
  session_id: string | null;
  session_title: string | null;
  occurred_at: string;
  effective_at: string;
  event_type: string;
  reason: string | null;
  actor_id: string | null;
  is_system_action: boolean;
  billing_result: string | null;
  credit_id: string | null;
  monthly_revenue_effect_cents: number | null;
}

export interface LeavingReportResponse {
  rows: LeavingReportRow[];
  total_monthly_revenue_effect_cents: number;
}

export function getLeavingReport(
  start: string,
  end: string,
): Promise<LeavingReportResponse> {
  const params = new URLSearchParams({ start, end });
  return apiFetch<LeavingReportResponse>(`/admin/reports/leaving?${params.toString()}`, {
    method: "GET",
  });
}
