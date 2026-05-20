/**
 * Typed admin BFF client.
 *
 * Wraps all /api/v2/admin/* endpoints. Types are hand-declared until
 * the openapi-typescript generator produces lib/api/generated/v2.d.ts.
 */

import { apiFetch } from "./client";

// ---------------------------------------------------------------------------
// Domain types
// ---------------------------------------------------------------------------

export interface AdminSessionView {
  session_id: string;
  coach_id: string;
  coach_name: string | null;
  title: string;
  location: string;
  start_at: string; // ISO 8601
  end_at: string; // ISO 8601
  capacity: number;
  enrolled_count: number;
  waitlist_count: number;
}

export interface AdminSessionList {
  sessions: AdminSessionView[];
}

export interface CreateSessionRequest {
  coach_id: string;
  title: string;
  location: string;
  start_at: string;
  end_at: string;
  capacity: number;
}

export type EnrollmentStatus = "active" | "paused" | "cancelled" | "withdrawn";

export interface AdminEnrollmentView {
  enrollment_id: string;
  session_id: string;
  student_id: string;
  parent_id: string;
  full_name: string;
  status: EnrollmentStatus;
  enrolled_at: string;
}

export interface AdminEnrollmentList {
  enrollments: AdminEnrollmentView[];
}

export interface CreateEnrollmentRequest {
  session_id: string;
  student_id: string;
  parent_id: string;
  full_name: string;
}

export interface TransferEnrollmentRequest {
  target_session_id: string;
}

export type WaitlistStatus = "waiting" | "skipped" | "promoted" | "removed";

export interface AdminWaitlistEntry {
  waitlist_id: string;
  session_id: string;
  student_id: string;
  parent_id: string;
  full_name: string;
  status: WaitlistStatus;
  position: number;
  added_at: string;
}

export interface AdminWaitlistList {
  waitlist: AdminWaitlistEntry[];
}

export interface PromoteWaitlistResponse {
  promoted_waitlist_id: string;
}

export type PaymentStatus =
  | "succeeded"
  | "pending"
  | "refunded"
  | "partially_refunded"
  | "failed"
  | "expired";

export interface AdminPaymentView {
  payment_id: string;
  parent_id: string;
  student_id: string | null;
  student_name: string | null;
  enrollment_id: string | null;
  session_id: string | null;
  period: string | null;
  amount_cents: number;
  discount_cents: number;
  final_amount_cents: number | null;
  currency: string;
  status: PaymentStatus;
  refunded_cents: number;
  invoice_number: string | null;
  payment_method: string | null;
  stripe_linked: boolean;
  created_at: string;
}

export interface AdminPaymentList {
  payments: AdminPaymentView[];
}

export interface RefundRequest {
  payment_id: string;
  amount_cents?: number;
  reason: string;
}

export interface RefundResponse {
  payment_id: string;
  stripe_refund_id: string;
  refunded_cents: number;
  total_refunded_cents: number;
}

export interface GenerateMonthlyPaymentsRequest {
  period: string;
}

export interface GenerateMonthlyPaymentsResponse {
  created: number;
  skipped_existing: number;
  skipped_no_charge: number;
  skipped_autopay: number;
  skipped_paused: number;
}

export interface MarkPaymentPaidRequest {
  payment_method: string;
  notes?: string;
}

export interface ApplyPaymentDiscountRequest {
  discount_cents: number;
}

export interface AdminEnrollmentQuote {
  snapshot_id: string;
  quote_expires_at?: string | null;
  amount_due_cents: number;
  monthly_price_cents: number;
  billing_period: string;
  total_eligible_classes_this_month: number;
  billable_remaining_classes_this_month: number;
  formula: string;
  included_occurrence_ids: string[];
  excluded_occurrences: Record<string, string>;
  policy_version: string;
  settings_version: string;
  schedule_signature: string | null;
}

export interface WithdrawalCreditPreviewResponse {
  credit_amount_cents: number;
  display_amount: string;
  total_classes: number;
  unused_classes: number;
  formula: string;
  message: string;
  no_credit_reason?: string | null;
}

export interface WithdrawalCreditApproveResponse {
  status: string;
  credit_amount_cents: number;
  credit_balance_cents: number;
}

export interface AdminPayoutView {
  payout_id: string;
  coach_id: string;
  amount_cents: number;
  period_start: string;
  period_end: string;
  paid_at: string | null;
}

export interface AdminPayoutList {
  payouts: AdminPayoutView[];
}

export interface AdminExpenseView {
  expense_id: string;
  category: string;
  amount_cents: number;
  note: string;
  incurred_on: string;
}

export interface AdminExpenseList {
  expenses: AdminExpenseView[];
}

export interface CreateExpenseRequest {
  category: "rent" | "equipment" | "salary" | "marketing" | "other";
  amount_cents: number;
  note?: string;
  incurred_on?: string;
}

export interface AdminRevenueResponse {
  by_month: Record<string, number>; // "YYYY-MM": cents
}

export interface AdminMessageView {
  message_id: string;
  sender_id: string;
  recipient_id: string | null; // null for broadcast
  body: string;
  sent_at: string;
  is_broadcast: boolean;
}

export interface AdminMessageList {
  messages: AdminMessageView[];
}

export interface BroadcastRequest {
  body: string;
}

export interface DmRequest {
  recipient_id: string;
  body: string;
}

export type AdminUserRole = "admin" | "coach" | "parent";

export interface AdminUserView {
  user_id: string;
  email: string;
  display_name: string;
  role: AdminUserRole;
  status: string;
}

export interface AdminUserList {
  users: AdminUserView[];
}

export interface AdminStudentView {
  student_id: string;
  full_name: string;
  parent_id: string;
  parent_name: string | null;
  parent_email: string | null;
  status: string;
  active_session_count: number;
  last_seen_at: string | null;
}

export interface AdminStudentList {
  students: AdminStudentView[];
}

export interface AdminPauseRequestView {
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

export interface AdminPauseRequestList {
  requests: AdminPauseRequestView[];
}

export interface AdminAuditLogView {
  audit_id: string;
  actor_id: string | null;
  action: string;
  entity_type: string | null;
  entity_id: string | null;
  created_at: string;
}

export interface AdminAuditLogList {
  logs: AdminAuditLogView[];
}

export interface DuesFollowupParentView {
  parent_id: string;
  parent_name: string | null;
  email: string | null;
  pending_count: number;
  followup_stage?: string;
  total_due_cents: number;
}

export interface DuesFollowupResponse {
  parents: DuesFollowupParentView[];
}

export interface SendDuesRemindersResponse {
  sent: number;
  blocked: boolean;
  reason: string | null;
}

export interface AdminAcademyView {
  academy_id: string;
  display_name: string;
  timezone: string;
  contact_email: string | null;
  contact_phone: string | null;
  hours_text: string | null;
  address: string | null;
}

export type UpdateAdminAcademyRequest = Partial<{
  display_name: string | null;
  timezone: string | null;
  contact_email: string | null;
  contact_phone: string | null;
  hours_text: string | null;
  address: string | null;
}>;

export interface AdminFeesView {
  default_monthly_cents: number | null;
  late_fee_cents: number | null;
  grace_days: number | null;
}

export type UpdateAdminFeesRequest = Partial<AdminFeesView>;

export interface AdminNotificationsView {
  dues_reminders: boolean;
  attendance_alerts: boolean;
  daily_digest_to_admin: boolean;
}

export type UpdateAdminNotificationsRequest = Partial<AdminNotificationsView>;

export interface AdminGatewayView {
  stripe_connected: boolean;
  stripe_account_id_masked: string | null;
  manual_methods: string[];
}

// ---------------------------------------------------------------------------
// Directory
// ---------------------------------------------------------------------------

export function listAdminUsers(role?: AdminUserRole): Promise<AdminUserList> {
  const q = role ? `?role=${encodeURIComponent(role)}` : "";
  return apiFetch<AdminUserList>(`/admin/users${q}`, { method: "GET" });
}

export function listAdminStudents(): Promise<AdminStudentList> {
  return apiFetch<AdminStudentList>("/admin/students", { method: "GET" });
}

export function updateAdminUserRole(
  userId: string,
  role: AdminUserRole
): Promise<AdminUserView> {
  return apiFetch<AdminUserView>(`/admin/users/${encodeURIComponent(userId)}/role`, {
    method: "PATCH",
    body: JSON.stringify({ role }),
  });
}

// ---------------------------------------------------------------------------
// Sessions
// ---------------------------------------------------------------------------

export function listAdminSessions(
  date?: string,
  opts?: { window?: "upcoming" },
): Promise<AdminSessionList> {
  const params = new URLSearchParams();
  if (date) params.set("date", date);
  if (opts?.window) params.set("window", opts.window);
  const q = params.toString() ? `?${params.toString()}` : "";
  return apiFetch<AdminSessionList>(`/admin/sessions${q}`, { method: "GET" });
}

export function createAdminSession(payload: CreateSessionRequest): Promise<AdminSessionView> {
  return apiFetch<AdminSessionView>("/admin/sessions", {
    method: "POST",
    body: JSON.stringify(payload),
  });
}

export function deleteAdminSession(sessionId: string): Promise<void> {
  return apiFetch<void>(`/admin/sessions/${sessionId}`, { method: "DELETE" });
}

// ---------------------------------------------------------------------------
// Enrollments
// ---------------------------------------------------------------------------

export function listSessionEnrollments(sessionId: string): Promise<AdminEnrollmentList> {
  return apiFetch<AdminEnrollmentList>(`/admin/sessions/${sessionId}/enrollments`, {
    method: "GET",
  });
}

export function createEnrollment(payload: CreateEnrollmentRequest): Promise<AdminEnrollmentView> {
  return apiFetch<AdminEnrollmentView>("/admin/enrollments", {
    method: "POST",
    body: JSON.stringify(payload),
  });
}

export function quoteAdminEnrollment(payload: {
  session_id: string;
  student_id?: string | null;
  start_date?: string | null;
}): Promise<AdminEnrollmentQuote> {
  return apiFetch<AdminEnrollmentQuote>("/admin/enrollments/quote", {
    method: "POST",
    body: JSON.stringify(payload),
  });
}

export function previewWithdrawalCredit(
  enrollmentId: string,
  payload: { withdrawal_date: string }
): Promise<WithdrawalCreditPreviewResponse> {
  return apiFetch<WithdrawalCreditPreviewResponse>(
    `/admin/enrollments/${enrollmentId}/withdrawal-credit/preview`,
    { method: "POST", body: JSON.stringify(payload) }
  );
}

export function approveWithdrawalCredit(
  enrollmentId: string,
  payload: {
    withdrawal_date: string;
    admin_note?: string;
    cancel_subscription_immediately?: boolean;
  }
): Promise<WithdrawalCreditApproveResponse> {
  return apiFetch<WithdrawalCreditApproveResponse>(
    `/admin/enrollments/${enrollmentId}/withdrawal-credit/approve`,
    { method: "POST", body: JSON.stringify(payload) }
  );
}

export function deleteEnrollment(enrollmentId: string): Promise<void> {
  return apiFetch<void>(`/admin/enrollments/${enrollmentId}`, { method: "DELETE" });
}

export function transferEnrollment(
  enrollmentId: string,
  payload: TransferEnrollmentRequest
): Promise<AdminEnrollmentView> {
  return apiFetch<AdminEnrollmentView>(`/admin/enrollments/${enrollmentId}/transfer`, {
    method: "POST",
    body: JSON.stringify(payload),
  });
}

export function pauseEnrollment(enrollmentId: string): Promise<void> {
  return apiFetch<void>(`/admin/enrollments/${enrollmentId}/pause`, { method: "POST" });
}

export function resumeEnrollment(enrollmentId: string): Promise<void> {
  return apiFetch<void>(`/admin/enrollments/${enrollmentId}/resume`, { method: "POST" });
}

// ---------------------------------------------------------------------------
// Waitlist
// ---------------------------------------------------------------------------

export function listSessionWaitlist(sessionId: string): Promise<AdminWaitlistList> {
  return apiFetch<AdminWaitlistList>(`/admin/sessions/${sessionId}/waitlist`, { method: "GET" });
}

export function promoteWaitlist(sessionId: string): Promise<PromoteWaitlistResponse> {
  return apiFetch<PromoteWaitlistResponse>(`/admin/sessions/${sessionId}/waitlist/promote`, {
    method: "POST",
  });
}

export function skipWaitlistEntry(waitlistId: string): Promise<void> {
  return apiFetch<void>(`/admin/waitlist/${waitlistId}/skip`, { method: "POST" });
}

export function deleteWaitlistEntry(waitlistId: string): Promise<void> {
  return apiFetch<void>(`/admin/waitlist/${waitlistId}`, { method: "DELETE" });
}

// ---------------------------------------------------------------------------
// Payments
// ---------------------------------------------------------------------------

export function listAdminPayments(): Promise<AdminPaymentList> {
  return apiFetch<AdminPaymentList>("/admin/payments", { method: "GET" });
}

export function refundPayment(payload: RefundRequest): Promise<RefundResponse> {
  return apiFetch<RefundResponse>("/admin/payments/refund", {
    method: "POST",
    body: JSON.stringify(payload),
  });
}

export function generateMonthlyPayments(
  payload: GenerateMonthlyPaymentsRequest
): Promise<GenerateMonthlyPaymentsResponse> {
  return apiFetch<GenerateMonthlyPaymentsResponse>("/admin/payments/generate-monthly", {
    method: "POST",
    body: JSON.stringify(payload),
  });
}

export function markPaymentPaid(paymentId: string, payload: MarkPaymentPaidRequest): Promise<void> {
  return apiFetch<void>(`/admin/payments/${paymentId}/mark-paid`, {
    method: "POST",
    body: JSON.stringify(payload),
  });
}

export function applyPaymentDiscount(
  paymentId: string,
  payload: ApplyPaymentDiscountRequest
): Promise<void> {
  return apiFetch<void>(`/admin/payments/${paymentId}/discount`, {
    method: "POST",
    body: JSON.stringify(payload),
  });
}

export function undoPaymentPaid(paymentId: string): Promise<void> {
  return apiFetch<void>(`/admin/payments/${paymentId}/undo-paid`, { method: "POST" });
}

// ---------------------------------------------------------------------------
// Finance
// ---------------------------------------------------------------------------

export function listPayouts(): Promise<AdminPayoutList> {
  return apiFetch<AdminPayoutList>("/admin/finance/payouts", { method: "GET" });
}

export function listExpenses(): Promise<AdminExpenseList> {
  return apiFetch<AdminExpenseList>("/admin/finance/expenses", { method: "GET" });
}

export function createExpense(payload: CreateExpenseRequest): Promise<AdminExpenseView> {
  return apiFetch<AdminExpenseView>("/admin/finance/expenses", {
    method: "POST",
    body: JSON.stringify(payload),
  });
}

export function getRevenue(): Promise<AdminRevenueResponse> {
  return apiFetch<AdminRevenueResponse>("/admin/finance/revenue", { method: "GET" });
}

// ---------------------------------------------------------------------------
// Messages / Comms
// ---------------------------------------------------------------------------

export function listAdminMessages(): Promise<AdminMessageList> {
  return apiFetch<AdminMessageList>("/admin/messages", { method: "GET" });
}

export function broadcastMessage(payload: BroadcastRequest): Promise<AdminMessageView> {
  return apiFetch<AdminMessageView>("/admin/messages/broadcast", {
    method: "POST",
    body: JSON.stringify(payload),
  });
}

export function sendDm(payload: DmRequest): Promise<AdminMessageView> {
  return apiFetch<AdminMessageView>("/admin/messages/dm", {
    method: "POST",
    body: JSON.stringify(payload),
  });
}

// ---------------------------------------------------------------------------
// Pause requests / audit / dues / reports
// ---------------------------------------------------------------------------

export function listAdminPauseRequests(): Promise<AdminPauseRequestList> {
  return apiFetch<AdminPauseRequestList>("/admin/pause-requests", { method: "GET" });
}

export function approvePauseRequest(pauseRequestId: string): Promise<AdminPauseRequestView> {
  return apiFetch<AdminPauseRequestView>(`/admin/pause-requests/${pauseRequestId}/approve`, {
    method: "POST",
  });
}

export function declinePauseRequest(pauseRequestId: string): Promise<AdminPauseRequestView> {
  return apiFetch<AdminPauseRequestView>(`/admin/pause-requests/${pauseRequestId}/decline`, {
    method: "POST",
  });
}

export function listAuditLogs(): Promise<AdminAuditLogList> {
  return apiFetch<AdminAuditLogList>("/admin/audit-logs", { method: "GET" });
}

export function listDuesFollowup(): Promise<DuesFollowupResponse> {
  return apiFetch<DuesFollowupResponse>("/admin/dues-followup", { method: "GET" });
}

export function sendDuesReminders(): Promise<SendDuesRemindersResponse> {
  return apiFetch<SendDuesRemindersResponse>("/admin/dues-reminders", { method: "POST" });
}

export function exportAdminReportCsv(reportName: string): Promise<string> {
  return apiFetch<string>(`/admin/reports/${encodeURIComponent(reportName)}.csv`, {
    method: "GET",
  });
}

// ---------------------------------------------------------------------------
// Settings
// ---------------------------------------------------------------------------

export function getAdminAcademy(): Promise<AdminAcademyView> {
  return apiFetch<AdminAcademyView>("/admin/academy", { method: "GET" });
}

export function updateAdminAcademy(
  payload: UpdateAdminAcademyRequest
): Promise<AdminAcademyView> {
  return apiFetch<AdminAcademyView>("/admin/academy", {
    method: "PATCH",
    body: JSON.stringify(payload),
  });
}

export function getAdminFees(): Promise<AdminFeesView> {
  return apiFetch<AdminFeesView>("/admin/academy/fees", { method: "GET" });
}

export function updateAdminFees(payload: UpdateAdminFeesRequest): Promise<AdminFeesView> {
  return apiFetch<AdminFeesView>("/admin/academy/fees", {
    method: "PATCH",
    body: JSON.stringify(payload),
  });
}

export function getAdminNotifications(): Promise<AdminNotificationsView> {
  return apiFetch<AdminNotificationsView>("/admin/academy/notifications", { method: "GET" });
}

export function updateAdminNotifications(
  payload: UpdateAdminNotificationsRequest
): Promise<AdminNotificationsView> {
  return apiFetch<AdminNotificationsView>("/admin/academy/notifications", {
    method: "PATCH",
    body: JSON.stringify(payload),
  });
}

export function getAdminGateway(): Promise<AdminGatewayView> {
  return apiFetch<AdminGatewayView>("/admin/academy/gateway", { method: "GET" });
}
