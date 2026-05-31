import { apiFetch } from "./client";

export interface ParentProfile {
  first_name: string;
  last_name: string;
  email?: string | null;
  phone: string;
}

export interface ChildProfile {
  first_name: string;
  last_name: string;
  date_of_birth: string;
  skill_level: "beginner" | "intermediate" | "advanced" | "";
}

export interface OnboardingApplication {
  application_id: string;
  status:
    | "DRAFT"
    | "CHECKOUT_PENDING"
    | "CHECKOUT_EXPIRED"
    | "PENDING_APPROVAL"
    | "CAPACITY_FAILED_REFUNDING"
    | "REFUNDED"
    | "CAPACITY_FAILED_REFUND_FAILED"
    | "ABANDONED";
  parent_profile: ParentProfile;
  child_profile: ChildProfile;
  selected_session_id: string | null;
  waiver_accepted: boolean;
  expires_at: string;
}

export interface ParentPayment {
  payment_id: string;
  amount_cents: number;
  currency: string;
  status: string;
  refunded_cents: number;
  created_at: string;
  session_id: string | null;
}

export interface ParentCredit {
  credit_id: string;
  type: string;
  status: string;
  amount_cents: number;
  remaining_amount_cents: number;
  currency: string;
  reason: string;
  expires_at?: string | null;
}

export interface ParentCreditBalance {
  balance_cents: number;
  credits: ParentCredit[];
}

export interface ParentAvailableSession {
  session_id: string;
  title: string;
  location: string;
  start_at: string;
  end_at: string;
  capacity: number;
  enrolled_count: number;
  available_seats: number;
  amount_cents: number;
}

export interface EnrollmentQuote {
  snapshot_id: string;
  quote_expires_at?: string | null;
  amount_due_cents: number;
  monthly_price_cents: number;
  billing_period: string;
  total_eligible_classes_this_month: number;
  billable_remaining_classes_this_month: number;
  formula: string;
  message: string;
  next_billing_amount_cents: number;
  next_billing_message: string;
}

export interface ParentChild {
  student_id: string;
  full_name: string;
  status: string;
  active_session_count: number;
  attended_count: number;
  absent_count: number;
}

export interface ParentEnrollment {
  enrollment_id: string;
  student_id: string;
  student_name: string;
  session_id: string;
  session_title: string;
  status: string;
  payment_mode: string | null;
  subscription_status: string | null;
}

export interface ParentAttendanceRecord {
  attendance_id: string;
  student_id: string;
  student_name: string;
  session_id: string;
  session_title: string;
  status: string;
  marked_at: string;
}

export interface ParentProgressNote {
  note_id: string;
  student_id: string;
  student_name: string;
  coach_id: string | null;
  body: string;
  created_at: string;
}

export interface ParentPauseRequest {
  pause_request_id: string;
  parent_id: string;
  enrollment_id: string;
  period: string;
  reason: string | null;
  status: "pending" | "approved" | "declined";
  requested_at: string;
  decided_at: string | null;
  decided_by: string | null;
}

export function startOnboarding(): Promise<OnboardingApplication> {
  return apiFetch("/parent/onboarding/start", { method: "POST", body: "{}" });
}

export function patchOnboarding(
  application_id: string,
  patch: {
    parent_profile?: Partial<ParentProfile>;
    child_profile?: Partial<ChildProfile>;
    selected_session_id?: string;
    accept_waiver?: boolean;
  }
): Promise<OnboardingApplication> {
  return apiFetch(`/parent/onboarding/${application_id}`, {
    method: "PATCH",
    body: JSON.stringify(patch),
  });
}

export function getOnboardingStatus(application_id: string): Promise<OnboardingApplication> {
  return apiFetch(`/parent/onboarding/${application_id}/status`, { method: "GET" });
}

export function startCheckout(payload: {
  application_id: string;
  success_url: string;
  cancel_url: string;
}): Promise<{ payment_id: string; redirect_url: string }> {
  return apiFetch("/parent/checkout/start", {
    method: "POST",
    body: JSON.stringify(payload),
  });
}

export function quoteEnrollment(payload: {
  student_id?: string | null;
  session_id: string;
  start_date?: string | null;
}): Promise<EnrollmentQuote> {
  return apiFetch("/parent/enrollments/quote", {
    method: "POST",
    body: JSON.stringify(payload),
  });
}

export function startAutopay(payload: {
  enrollment_id: string;
  success_url: string;
  cancel_url: string;
}): Promise<{ subscription_id: string; redirect_url: string }> {
  return apiFetch("/parent/autopay/start", {
    method: "POST",
    body: JSON.stringify(payload),
  });
}

export function openBillingPortal(payload: {
  return_url: string;
}): Promise<{ redirect_url: string }> {
  return apiFetch("/parent/billing/portal", {
    method: "POST",
    body: JSON.stringify(payload),
  });
}

export function getCheckoutStatus(checkoutSessionId: string): Promise<{
  checkout_session_id: string;
  payment_id: string | null;
  status: string;
  parent_id: string;
}> {
  return apiFetch(`/parent/checkout/status/${checkoutSessionId}`, { method: "GET" });
}

export function listAvailableParentSessions(): Promise<{ sessions: ParentAvailableSession[] }> {
  return apiFetch("/parent/sessions/available", { method: "GET" });
}

export function listParentPayments(): Promise<{ payments: ParentPayment[] }> {
  return apiFetch("/parent/payments", { method: "GET" });
}

export function listParentCredits(): Promise<ParentCreditBalance> {
  return apiFetch("/parent/credits", { method: "GET" });
}

export function listParentChildren(): Promise<{ children: ParentChild[] }> {
  return apiFetch("/parent/children", { method: "GET" });
}

export function listParentEnrollments(): Promise<{ enrollments: ParentEnrollment[] }> {
  return apiFetch("/parent/enrollments", { method: "GET" });
}

export function listParentAttendance(): Promise<{ records: ParentAttendanceRecord[] }> {
  return apiFetch("/parent/attendance", { method: "GET" });
}

export function listParentProgress(): Promise<{ notes: ParentProgressNote[] }> {
  return apiFetch("/parent/progress", { method: "GET" });
}

export function listParentPauseRequests(): Promise<{ requests: ParentPauseRequest[] }> {
  return apiFetch("/parent/pause-requests", { method: "GET" });
}

export function createParentPauseRequest(payload: {
  enrollment_id: string;
  period: string;
  reason?: string;
}): Promise<ParentPauseRequest> {
  return apiFetch("/parent/pause-requests", {
    method: "POST",
    body: JSON.stringify(payload),
  });
}

// --- Waivers ---

export type ParentWaiverStatus = "signed" | "pending" | "outdated" | "not_required";

export interface ParentWaiverStudentView {
  student_id: string;
  student_name: string;
  status: ParentWaiverStatus;
  signed_at: string | null;
  waiver_version: string | null;
}

export interface ParentWaiverCurrentView {
  required: boolean;
  waiver_template_id: string | null;
  title: string | null;
  version: string | null;
  body: string | null;
  students: ParentWaiverStudentView[];
}

export function getParentCurrentWaiver(): Promise<ParentWaiverCurrentView> {
  return apiFetch("/parent/waivers/current", { method: "GET" });
}

export function acceptParentWaiver(payload: {
  signer_name: string | null;
}): Promise<ParentWaiverCurrentView> {
  return apiFetch("/parent/waivers/accept", {
    method: "POST",
    body: JSON.stringify(payload),
  });
}
