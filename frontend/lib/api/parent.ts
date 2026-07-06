import { apiFetch } from "./client";
import type { SkillStatus } from "./curriculum";

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
  stripe_invoice_id?: string | null;
  stripe_payment_intent_id?: string | null;
  invoice_id?: string | null;
  invoice_period?: string | null;
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
  /** @deprecated Not populated by the v2 BFF; autopay state lives in autopay_enrollment_status. Do not read. */
  subscription_status: string | null;
  autopay_enrollment_status?: string | null;
  last_attempt_outcome?: string | null;
  last_attempt_at?: string | null;
  last_failure_code?: string | null;
  autopay_payment_method_type?: string | null;
  autopay_payment_method_label?: string | null;
  autopay_payment_method_last4?: string | null;
  autopay_setup_status?: string | null;
}

export interface ParentInvoice {
  invoice_id: string;
  period: string;
  status: string;
  total_cents: number;
  balance_due_cents: number;
  currency: string;
  due_date: string;
  pdf_url: string | null;
  created_at: string;
}

export interface ParentInvoiceLine {
  description: string;
  label?: string | null;
  quantity: number;
  unit_amount_cents: number;
  amount_cents: number;
}

export interface ParentInvoiceDetail extends ParentInvoice {
  lines: ParentInvoiceLine[];
}

export interface ParentAttendanceRecord {
  attendance_id: string;
  student_id: string;
  student_name: string;
  session_id: string;
  session_title: string;
  status: string;
  marked_at: string;
  coach_name: string | null;
}

export interface ParentProgressNote {
  note_id: string;
  student_id: string;
  student_name: string;
  session_id: string | null;
  session_title: string | null;
  coach_id: string | null;
  coach_name: string | null;
  body: string;
  created_at: string;
}

export interface ParentSkillUpdate {
  skill_id: string;
  skill_name: string;
  status: SkillStatus;
  updated_at: string;
}

export interface ParentPracticeResourceLink {
  kind: "YOUTUBE";
  title: string;
  url: string;
}

export interface ParentPracticeResource {
  skill_id: string;
  skill_name: string;
  resource_links: ParentPracticeResourceLink[];
}

export interface ParentScheduleEntry {
  occurrence_id: string;
  session_id: string;
  session_title: string;
  location: string | null;
  start_at: string;
  end_at: string;
  status: string;
  coach_name: string | null;
}

export interface ParentScheduleResponse {
  entries: ParentScheduleEntry[];
  total: number;
  limit: number;
  offset: number;
}

export interface ParentPauseRequest {
  pause_request_id: string;
  parent_id: string;
  enrollment_id: string;
  period: string;
  pause_kind: "fixed" | "indefinite";
  resume_on: string | null;
  review_on: string | null;
  reason: string | null;
  status: "pending" | "approved" | "declined";
  created_at: string;
  decided_at: string | null;
  decided_by: string | null;
}

export interface RegistrationWaiver {
  configured: boolean;
  version: string | null;
  body: string | null;
}

export function getRegistrationWaiver(): Promise<RegistrationWaiver> {
  return apiFetch("/parent/onboarding/waiver", { method: "GET" });
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
  },
): Promise<OnboardingApplication> {
  return apiFetch(`/parent/onboarding/${application_id}`, {
    method: "PATCH",
    body: JSON.stringify(patch),
  });
}

export function getOnboardingStatus(
  application_id: string,
): Promise<OnboardingApplication> {
  return apiFetch(`/parent/onboarding/${application_id}/status`, {
    method: "GET",
  });
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
}): Promise<{ subscription_id: string; checkout_session_id: string; redirect_url: string }> {
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
  return apiFetch(`/parent/checkout/status/${checkoutSessionId}`, {
    method: "GET",
  });
}

export function listAvailableParentSessions(): Promise<{
  sessions: ParentAvailableSession[];
}> {
  return apiFetch("/parent/sessions/available", { method: "GET" });
}

export function listParentPayments(): Promise<{ payments: ParentPayment[] }> {
  return apiFetch("/parent/payments", { method: "GET" });
}

export function listParentInvoices(): Promise<{ invoices: ParentInvoice[] }> {
  return apiFetch("/parent/invoices", { method: "GET" });
}

export function getParentInvoice(invoiceId: string): Promise<ParentInvoiceDetail> {
  return apiFetch(`/parent/invoices/${encodeURIComponent(invoiceId)}`, { method: "GET" });
}

export function startParentInvoicePayment(
  invoiceId: string,
  payload: {
    success_url: string;
    cancel_url: string;
  },
): Promise<{ invoice_id: string; redirect_url: string }> {
  return apiFetch(`/parent/invoices/${encodeURIComponent(invoiceId)}/pay`, {
    method: "POST",
    body: JSON.stringify(payload),
  });
}

export function startParentBalancePayment(payload: {
  success_url: string;
  cancel_url: string;
}): Promise<{ redirect_url: string }> {
  return apiFetch("/parent/invoices/pay-balance", {
    method: "POST",
    body: JSON.stringify(payload),
  });
}

export function listParentCredits(): Promise<ParentCreditBalance> {
  return apiFetch("/parent/credits", { method: "GET" });
}

export function listParentChildren(): Promise<{ children: ParentChild[] }> {
  return apiFetch("/parent/children", { method: "GET" });
}

export function listParentEnrollments(): Promise<{
  enrollments: ParentEnrollment[];
}> {
  return apiFetch("/parent/enrollments", { method: "GET" });
}

export function listParentAttendance(): Promise<{
  records: ParentAttendanceRecord[];
}> {
  return apiFetch("/parent/attendance", { method: "GET" });
}

export function listParentProgress(): Promise<{ notes: ParentProgressNote[] }> {
  return apiFetch("/parent/progress", { method: "GET" });
}

export function listSkillUpdates(studentId: string): Promise<ParentSkillUpdate[]> {
  return apiFetch<{ updates: ParentSkillUpdate[] }>(
    `/parent/students/${encodeURIComponent(studentId)}/skill-updates`,
    { method: "GET" },
  ).then((d) => d.updates);
}

export function listPracticeResources(
  studentId: string,
): Promise<ParentPracticeResource[]> {
  return apiFetch<{ resources: ParentPracticeResource[] }>(
    `/parent/students/${encodeURIComponent(studentId)}/practice-resources`,
    { method: "GET" },
  ).then((d) => d.resources);
}

export function listParentPauseRequests(): Promise<{
  requests: ParentPauseRequest[];
}> {
  return apiFetch("/parent/pause-requests", { method: "GET" });
}

export function getChildSchedule(
  studentId: string,
): Promise<ParentScheduleResponse> {
  return apiFetch(
    `/parent/children/${encodeURIComponent(studentId)}/schedule`,
    { method: "GET" },
  );
}

export interface ParentAcademy {
  display_name: string;
  timezone: string | null;
  contact_email: string | null;
  contact_phone: string | null;
  hours_text: string | null;
  address: string | null;
  logo_url: string | null;
}

export function getParentAcademy(): Promise<ParentAcademy> {
  return apiFetch("/parent/academy", { method: "GET" });
}

export function createParentPauseRequest(payload: {
  enrollment_id: string;
  period?: string;
  pause_kind: "fixed" | "indefinite";
  resume_on?: string | null;
  review_on?: string | null;
  reason?: string;
}): Promise<ParentPauseRequest> {
  return apiFetch("/parent/pause-requests", {
    method: "POST",
    body: JSON.stringify(payload),
  });
}

// --- Waivers ---

export type ParentWaiverStatus =
  | "signed"
  | "pending"
  | "outdated"
  | "not_required";

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

// --- Self-service requests (absences, makeups, trials, self-cancel) ---

export interface AbsenceNoticeView {
  notice_id: string;
  student_id: string;
  occurrence_id: string;
  session_id: string;
  submitted_by: string;
  submitted_at: string;
  notice_window_met: boolean;
}

export function listParentAbsences(): Promise<{ absences: AbsenceNoticeView[] }> {
  return apiFetch("/parent/absences", { method: "GET" });
}

export function submitAbsenceNotice(payload: {
  student_id: string;
  occurrence_id: string;
}): Promise<AbsenceNoticeView> {
  return apiFetch("/parent/absences", {
    method: "POST",
    body: JSON.stringify(payload),
  });
}

export interface MakeupRequestView {
  request_id: string;
  student_id: string;
  missed_occurrence_id: string;
  requested_target_occurrence_id: string | null;
  status: string;
  expires_at: string;
  denial_reason: string | null;
  decided_by: string | null;
  decided_at: string | null;
  approved_target_occurrence_id: string | null;
  created_at: string;
}

export function listParentMakeups(): Promise<{ makeups: MakeupRequestView[] }> {
  return apiFetch("/parent/makeups", { method: "GET" });
}

export function submitMakeupRequest(payload: {
  student_id: string;
  missed_occurrence_id: string;
  requested_target_occurrence_id?: string | null;
}): Promise<MakeupRequestView> {
  return apiFetch("/parent/makeups", {
    method: "POST",
    body: JSON.stringify(payload),
  });
}

export interface MakeupTargetView {
  occurrence_id: string;
  session_id: string;
  title: string;
  start_at: string;
  end_at: string;
  open_slots: number;
}

export function listEligibleMakeupTargets(params: {
  student_id: string;
  missed_occurrence_id: string;
}): Promise<{ targets: MakeupTargetView[] }> {
  const query = new URLSearchParams({
    student_id: params.student_id,
    missed_occurrence_id: params.missed_occurrence_id,
  });
  return apiFetch(`/parent/makeups/eligible-targets?${query.toString()}`, {
    method: "GET",
  });
}

export type TrialRequestStudentRef = "prospective" | "existing_student";

export interface TrialRequestView {
  request_id: string;
  student_ref: string;
  student_id: string | null;
  prospective_child_name: string | null;
  prospective_child_dob: string | null;
  requested_session_id: string;
  preferred_start: string;
  preferred_end: string;
  status: string;
  assigned_occurrence_id: string | null;
  linked_application_id: string | null;
  denial_reason: string | null;
  decided_by: string | null;
  decided_at: string | null;
  created_at: string;
}

export function listParentTrialRequests(): Promise<{ trials: TrialRequestView[] }> {
  return apiFetch("/parent/trial-requests", { method: "GET" });
}

export function submitTrialRequest(payload: {
  student_ref: TrialRequestStudentRef;
  requested_session_id: string;
  preferred_start: string;
  preferred_end: string;
  student_id?: string | null;
  prospective_child_name?: string | null;
  prospective_child_dob?: string | null;
}): Promise<TrialRequestView> {
  return apiFetch("/parent/trial-requests", {
    method: "POST",
    body: JSON.stringify(payload),
  });
}

export interface CancellationPreview {
  allowed: boolean;
  notice_met: boolean;
  fee_cents: number;
  effective_timing: string;
  policy: Record<string, unknown>;
  blocked_reason: string | null;
}

export function getCancellationPreview(
  enrollmentId: string,
): Promise<CancellationPreview> {
  return apiFetch(
    `/parent/enrollments/${encodeURIComponent(enrollmentId)}/cancellation-preview`,
    { method: "GET" },
  );
}

export interface SelfCancelResult {
  enrollment_id: string;
  status: string;
  fee_cents: number;
  effective_timing: string;
  cancelled_at: string;
}

export function selfCancelEnrollment(
  enrollmentId: string,
  payload: { reason: string },
): Promise<SelfCancelResult> {
  return apiFetch(
    `/parent/enrollments/${encodeURIComponent(enrollmentId)}/self-cancel`,
    {
      method: "POST",
      body: JSON.stringify(payload),
    },
  );
}
