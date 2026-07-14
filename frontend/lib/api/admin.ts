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
  days_of_week: string[];
  start_time: string | null;
  end_time: string | null;
  timezone: string | null;
  capacity: number;
  amount_cents?: number | null;
  status: "scheduled" | "cancelled" | "completed";
  enrolled_count: number;
  waitlist_count: number;
}

export interface AdminSessionList {
  sessions: AdminSessionView[];
}

export interface AdminSessionOccurrenceView {
  occurrence_id: string;
  session_id: string;
  start_at: string;
  end_at: string;
  status: "scheduled" | "cancelled" | "completed";
  scheduled_coach_id: string;
  actual_coach_id: string | null;
  substitute_coach_id: string | null;
  attendance_marked_count: number;
  attendance_marked_by: string[];
  attendance_last_marked_at: string | null;
  coach_attendance: AdminCoachAttendanceView[];
}

export interface AdminSessionOccurrenceList {
  occurrences: AdminSessionOccurrenceView[];
}

export interface AdminCoachAttendanceView {
  attendance_id: string;
  occurrence_id: string;
  coach_id: string;
  status: "present" | "absent";
  role: "lead" | "assistant";
  source: "coach_self" | "admin";
  marked_by: string;
  marked_at: string;
  rate_override_minor: number | null;
  note: string;
}

export interface UpdateSessionOccurrenceCoachRequest {
  actual_coach_id?: string | null;
  substitute_coach_id?: string | null;
  reason: string;
}

export interface UpdateOccurrenceReplacementRequest {
  replacement_coach_id?: string | null;
  reason?: string | null;
}

export interface AddSessionReplacementRequest {
  date: string;
  replacement_coach_id: string;
  reason?: string | null;
}

export interface UpdateOccurrenceCoachAttendanceRequest {
  coach_id: string;
  status: "present" | "absent";
  role: "lead" | "assistant";
  rate_override_minor?: number | null;
  note?: string;
}

export interface CreateSessionRequest {
  coach_id: string;
  title: string;
  location: string;
  start_at?: string | null;
  end_at?: string | null;
  days_of_week?: string[];
  start_time?: string | null;
  end_time?: string | null;
  timezone?: string | null;
  capacity: number;
  amount_cents?: number | null;
}

export interface EditSessionRequest {
  coach_id?: string;
  title?: string;
  location?: string;
  start_at?: string | null;
  end_at?: string | null;
  days_of_week?: string[];
  start_time?: string | null;
  end_time?: string | null;
  timezone?: string | null;
  capacity?: number;
  amount_cents?: number | null;
  reason?: string;
}

export type EnrollmentStatus = "active" | "paused" | "cancelled" | "withdrawn";

export interface AdminEnrollmentView {
  enrollment_id: string;
  session_id: string;
  student_id: string;
  parent_id: string;
  full_name: string;
  status: EnrollmentStatus;
  enrolled_at: string | null;
  level?: string | null;
  pathway_program_id?: string | null;
  pathway_level_id?: string | null;
  pathway_level_sequence?: number | null;
  pathway_level_name?: string | null;
  pathway_placement_status?: string;
  pathway_skills_total?: number;
  pathway_skills_completed?: number;
  pathway_skills_ready_for_test?: number;
  pathway_completion_percentage?: number;
  pathway_next_action?: string;
  dues_status?: "current" | "due" | "overdue";
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
  effective_date: string;
  reason?: string;
}

export interface PauseEnrollmentRequest {
  effective_date: string;
  resume_on?: string | null;
  review_on?: string | null;
  reason?: string;
}

export interface WithdrawEnrollmentRequest {
  effective_date: string;
  outcome?: "credit" | "refund" | "adjustment";
  reason: string;
}

export interface RemoveEnrollmentRequest {
  effective_date: string;
  reason: string;
}

export interface EnrollmentEventView {
  event_id: string;
  event_type: string;
  effective_date: string;
  reason: string | null;
  billing_policy: string | null;
  billing_result: string | null;
  credit_id: string | null;
  refund_id: string | null;
  metadata: Record<string, string>;
}

export interface EnrollmentEventsResponse {
  enrollment_id: string;
  events: EnrollmentEventView[];
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

export interface AdminGlobalWaitlistSession {
  session_id: string;
  title: string;
  location: string;
  start_at: string;
  capacity: number;
  enrolled_count: number;
  waitlist_count: number;
  entries: AdminWaitlistEntry[];
}

export interface AdminGlobalWaitlistList {
  total_waitlisted: number;
  sessions: AdminGlobalWaitlistSession[];
}

export interface PromoteWaitlistResponse {
  promoted_waitlist_id: string;
}

export type PaymentStatus =
  | "succeeded"
  | "paid"
  | "pending"
  | "refunded"
  | "partially_refunded"
  | "failed"
  | "expired"
  | "waived";

export type AdminPaymentStatus = PaymentStatus | "partially_paid";

export interface AdminPaymentView {
  payment_id: string;
  invoice_id?: string | null;
  parent_id: string;
  parent_name?: string | null;
  student_id: string | null;
  student_name: string | null;
  enrollment_id: string | null;
  session_id: string | null;
  period: string | null;
  amount_cents: number;
  discount_cents: number;
  final_amount_cents: number | null;
  amount_received_cents: number;
  paid_amount_cents: number;
  balance_due_cents: number | null;
  overpayment_credit_cents: number;
  currency: string;
  status: AdminPaymentStatus;
  refunded_cents: number;
  invoice_number: string | null;
  payment_method: string | null;
  stripe_linked: boolean;
  stripe_customer_id?: string | null;
  stripe_checkout_session_id?: string | null;
  stripe_subscription_id?: string | null;
  stripe_invoice_id?: string | null;
  stripe_payment_intent_id?: string | null;
  reconciliation_status?: string | null;
  created_at: string;
  paid_at?: string | null;
}

export interface AdminPaymentList {
  payments: AdminPaymentView[];
  total?: number | null;
  limit?: number | null;
  offset?: number | null;
}

export interface AdminPaymentListFilters {
  date_from?: string;
  date_to?: string;
  status?: string;
  method?: string;
  q?: string;
  limit?: number;
  offset?: number;
}

export interface AdminPaymentFeedItem {
  payment_id: string;
  parent_id: string;
  parent_name: string | null;
  amount_cents: number;
  refunded_cents: number;
  currency: string;
  status: string;
  payment_method: string | null;
  paid_at: string;
}

export interface AdminPaymentFeedResponse {
  payments: AdminPaymentFeedItem[];
}

export interface AdminFamilyLastPaymentRow {
  parent_id: string;
  parent_name: string | null;
  last_paid_at: string;
  amount_cents: number;
  payment_method: string | null;
  status: string;
}

export interface AdminFamilyLastPaymentsResponse {
  rows: AdminFamilyLastPaymentRow[];
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
  repaired_orphan_keys: number;
  repaired_partial_invoices: number;
  failed_repair: number;
  skipped_details: MonthlyGenerationSkippedDetail[];
}

export interface MonthlyGenerationSkippedDetail {
  enrollment_id: string;
  student_id: string;
  student_name: string | null;
  reason_code: string;
  source: string;
  billing_period: string;
  resume_on: string | null;
  review_on: string | null;
  expires_on: string | null;
  needs_review: boolean;
  metadata: Record<string, string>;
}

export interface MarkPaymentPaidRequest {
  payment_method: "cash" | "check" | "zelle" | "venmo" | "bank_transfer" | "other";
  amount_received_cents?: number;
  reference_number?: string;
  notes?: string;
  /** ISO date (YYYY-MM-DD) the money was actually received. */
  payment_date?: string;
}

export interface ApplyPaymentDiscountRequest {
  discount_cents: number;
  reason: string;
}

export interface ReconcileStripeBillingRequest {
  parent_id: string;
  enrollment_id: string;
  stripe_customer_id?: string | null;
  stripe_checkout_session_id: string;
  reason: string;
}

export interface ReconcileStripeBillingResponse {
  ok: boolean;
  mismatch_state: string | null;
  payment_id: string | null;
  stripe_customer_id: string | null;
  stripe_checkout_session_id: string | null;
  stripe_subscription_id: string | null;
  stripe_invoice_id: string | null;
  stripe_payment_intent_id: string | null;
  audit_id: string | null;
}

export interface BillingReconciliationMismatch {
  code: string;
  message: string;
  stripe_value?: unknown;
  local_value?: unknown;
}

export interface BillingManualReviewCandidate {
  invoice_id: string;
  parent_id: string;
  student_id: string | null;
  enrollment_id: string | null;
  period: string | null;
  amount_cents: number;
  currency: string;
  status: string;
  reason: string;
}

export interface BillingReconciliationReport {
  result: string;
  stripe_invoice_id: string | null;
  payment_intent_id: string | null;
  stripe_customer_id: string | null;
  local_invoice_id: string | null;
  ledger_payment_id: string | null;
  payment_allocation_id: string | null;
  mismatches: BillingReconciliationMismatch[];
  manual_review_candidates: BillingManualReviewCandidate[];
  checked_at: string;
}

export interface BillingWebhookEvent {
  event_id: string;
  event_type: string;
  status: string;
  object_id: string | null;
  object_type: string | null;
  received_at: string | null;
  last_attempt_at: string | null;
  retry_count: number;
  error_message: string | null;
}

export interface BillingWebhookQueue {
  events: BillingWebhookEvent[];
}

export interface AdminBillingProductView {
  product_id: string;
  name: string;
  default_unit_amount_cents: number;
  line_type: string;
  active: boolean;
  created_at: string;
  updated_at: string;
}

export interface AdminBillingProductList {
  products: AdminBillingProductView[];
}

export interface CreateBillingProductRequest {
  name: string;
  default_unit_amount_cents: number;
  line_type: string;
}

export interface UpdateBillingProductRequest {
  name?: string;
  default_unit_amount_cents?: number;
  line_type?: string;
  active?: boolean;
}

export interface InvoiceLineView {
  line_id?: string | null;
  invoice_id?: string | null;
  line_type?: string | null;
  description: string;
  quantity?: number | null;
  unit_amount_cents?: number | null;
  amount_cents: number;
  source_type?: string | null;
  source_id?: string | null;
}

export interface InvoiceLineMutationResponse extends InvoiceLineView {
  line_id: string;
  invoice_id: string;
  line_type: string;
  quantity: number;
  unit_amount_cents: number;
  invoice_total_cents: number;
  invoice_balance_due_cents: number;
  invoice_status: string;
}

export interface InvoiceAllocationView {
  payment_id: string;
  amount_cents: number;
}

export interface InvoiceCreditUsageView {
  credit_id: string;
  amount_cents: number;
}

export interface AdminInvoiceDetail {
  invoice_id?: string;
  invoice_number: string;
  period: string;
  lines: InvoiceLineView[];
  total_cents?: number;
  subtotal_cents?: number;
  discount_cents?: number;
  balance_due_cents?: number;
  due_amount_cents: number;
  paid_amount_cents: number;
  status: string;
  delivery_status: "not_sent" | "sent" | "delivery_failed" | string;
  sent_at: string | null;
  last_sent_at: string | null;
  allocations: InvoiceAllocationView[];
  credit_usage: InvoiceCreditUsageView[];
  invoice_pdf_artifact_id: string | null;
  receipt_artifact_id: string | null;
}

export interface AdminLedgerInvoiceView {
  invoice_id: string;
  academy_id: string;
  parent_id: string;
  student_id: string | null;
  enrollment_id: string | null;
  period: string;
  status: "draft" | "open" | "partially_paid" | "paid" | "void" | string;
  subtotal_cents: number;
  discount_cents: number;
  total_cents: number;
  balance_due_cents: number;
  currency: string;
  due_date: string;
  pdf_artifact_id: string | null;
  delivery_status: "not_sent" | "sent" | "delivery_failed" | string;
  sent_at: string | null;
  last_sent_at: string | null;
  finalized_at: string | null;
  created_at: string;
  updated_at: string;
}

export interface CreateStudentInvoiceRequest {
  parent_id: string;
  period: string;
  due_date: string;
  enrollment_id?: string | null;
}

export interface AddInvoiceLineRequest {
  product_id?: string | null;
  description: string;
  line_type: string;
  quantity?: number;
  unit_amount_cents: number;
}

export interface ApplyInvoiceAdjustmentRequest {
  description: string;
  amount_cents: number;
  reason: string;
}

export interface SendInvoiceResponse {
  invoice_id: string;
  delivery_status: "not_sent" | "sent" | "delivery_failed" | string;
  sent_at: string | null;
  last_sent_at: string | null;
  checkout_url: string | null;
}

export interface ChargeAutopayResponse {
  invoice_id: string;
  success: boolean;
  status: string;
  balance_due_cents: number;
  requires_action: boolean;
  decline_code: string | null;
}

export interface RecordManualPaymentRequest {
  amount_cents: number;
  payment_method?: string;
  reference_number?: string | null;
  notes?: string;
}

export interface RecordManualPaymentResponse {
  invoice_id: string;
  payment_id: string;
  invoice_status: string;
  balance_due_cents: number;
}

export interface InvoiceRefundRequest {
  amount_cents?: number;
  reason: string;
}

export interface InvoiceRefundResponse {
  invoice_id: string;
  payment_id: string;
  stripe_refund_id: string;
  refunded_cents: number;
  total_refunded_cents: number;
}

export interface VoidInvoiceResponse {
  ok: boolean;
}

export interface VoidInvoiceRequest {
  reason: string;
}

export interface GenerateInvoiceArtifactResponse {
  artifact_id: string;
  artifact_type: "invoice_pdf" | "receipt";
  status: "generated";
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
  expected_revenue_cents?: number | null;
  students_count?: number | null;
  sessions_count?: number | null;
  rule_label?: string | null;
}

export interface AdminPayoutList {
  payouts: AdminPayoutView[];
}

export type CoachPayBillingUnit = "per_session" | "per_hour" | "percent_of_revenue";
export type CoachRateTimelineIssueType =
  | "gap"
  | "overlap"
  | "duplicate_effective_from"
  | "duplicate_active_rows"
  | "multiple_open_ended_rows"
  | "invalid_window"
  | "malformed_history";

export interface AdminCoachPayRateView {
  rate_id: string;
  coach_id: string;
  billing_unit: CoachPayBillingUnit;
  amount_cents: number;
  percent: number | null;
  currency: string;
  effective_from: string;
  effective_until: string | null;
  status: "active" | "superseded";
}

export interface AdminCoachPayRateTimelineIssue {
  issue_type: CoachRateTimelineIssueType;
  message: string;
  rate_ids: string[];
  starts_at: string | null;
  ends_at: string | null;
}

export interface AdminCoachPayRateTimelineDiagnostics {
  coach_id: string;
  has_blocking_issues: boolean;
  issues: AdminCoachPayRateTimelineIssue[];
}

export interface AdminCoachPayRateList {
  rates: AdminCoachPayRateView[];
  diagnostics?: AdminCoachPayRateTimelineDiagnostics;
}

export interface SetCoachPayRateRequest {
  billing_unit: CoachPayBillingUnit;
  amount_cents?: number;
  percent?: number | null;
  currency?: string;
  effective_from?: string | null;
}

export interface RepairCoachPayRateWindowRequest {
  billing_unit: CoachPayBillingUnit;
  amount_cents?: number;
  percent?: number | null;
  currency?: string;
  effective_from: string;
  effective_until: string;
  reason: string;
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

export interface EditExpenseRequest {
  category?: CreateExpenseRequest["category"];
  amount_cents?: number;
  note?: string;
  incurred_on?: string;
  reason?: string;
}

export interface AdminRevenueResponse {
  by_month: Record<string, number>; // "YYYY-MM": cents
}

export interface AdminReportsKpiResponse {
  active_students: number;
  attendance_rate_30d: number;
  dues_collected_mtd_cents: number;
  pending_waivers: number;
}

export interface AdminReportsAttendanceSummary {
  present_count: number;
  recorded_count: number;
  attendance_rate: number | null;
  empty: boolean;
}

export interface AdminReportsSessionsSummary {
  scheduled_count: number;
  completed_count: number;
  cancelled_count: number;
  enrolled_seats: number;
  capacity: number;
  capacity_utilization: number | null;
  waitlist_count: number;
  empty: boolean;
}

export interface AdminReportsExpenseCategory {
  category: string;
  amount_cents: number;
  count: number;
}

export interface AdminReportsExpensesSummary {
  total_cents: number;
  by_category: AdminReportsExpenseCategory[];
}

export interface AdminReportsAgingFamily {
  family_id: string;
  family_name: string | null;
  amount_cents: number;
}

export interface AdminReportsCollectionsAgingBucket {
  label: string;
  amount_cents: number;
  family_count: number;
  families: AdminReportsAgingFamily[];
}

export interface AdminReportsCollectionsRisk {
  overdue_family_count: number;
  overdue_cents: number;
  failed_payment_count: number;
  partial_payment_count: number;
  aging_buckets: AdminReportsCollectionsAgingBucket[];
}

export interface AdminReportsProfitAndLoss {
  revenue_cents: number;
  coach_payroll_cents: number | null;
  rent_cents: number;
  misc_expenses_cents: number;
  net_profit_cents: number | null;
  profit_margin: number | null;
}

export interface AdminReportsPayrollSummary {
  estimated_cents: number | null;
  approved_cents: number | null;
  paid_cents: number | null;
  unpaid_cents: number | null;
  blocked_by: string | null;
}

export interface AdminReportsDashboardResponse {
  period: string;
  cash_collected_cents: number;
  billed_cents: number;
  collection_rate: number | null;
  outstanding_dues_cents: number;
  attendance: AdminReportsAttendanceSummary;
  sessions: AdminReportsSessionsSummary;
  expenses: AdminReportsExpensesSummary;
  collections_risk: AdminReportsCollectionsRisk;
  profit_and_loss: AdminReportsProfitAndLoss;
  payroll: AdminReportsPayrollSummary;
  empty_states: string[];
}

export interface AdminSessionEconomicsSummary {
  expected_revenue_cents: number;
  paid_cents: number;
  unpaid_cents: number;
  coach_payroll_cents: number;
  rent_cents: number;
  other_expenses_cents: number;
  expected_profit_cents: number;
  profit_margin: number | null;
}

export interface AdminSessionEconomicsRow {
  session_id: string;
  title: string;
  coach_name: string | null;
  active_enrollment_count: number;
  paid_student_count: number;
  unpaid_student_count: number;
  monthly_fee_cents: number;
  payable_occurrence_count: number;
  expected_revenue_per_occurrence_cents: number;
  expected_revenue_cents: number;
  paid_cents: number;
  unpaid_cents: number;
  coach_payroll_cents: number;
  rent_cents: number;
  other_expenses_cents: number;
  expected_profit_cents: number;
  profit_margin: number | null;
}

export interface AdminSessionEconomicsResponse {
  period: string;
  summary: AdminSessionEconomicsSummary;
  sessions: AdminSessionEconomicsRow[];
  empty_states: string[];
}

export interface AdminMessageView {
  message_id: string;
  kind: "dm" | "announcement" | string;
  sender_id: string;
  recipient_id: string | null; // null for broadcast
  body: string;
  created_at?: string;
  sent_at: string;
  is_broadcast: boolean;
  scope_type?: string | null;
  scope_label?: string | null;
  recipient_count?: number | null;
  delivery_status?: string | null;
}

export interface AdminMessageList {
  messages: AdminMessageView[];
}

export type AdminWaiverStatus = "signed" | "pending" | "expiring" | "outdated";

export interface AdminWaiverSummary {
  signed_current: number;
  pending_signature: number;
  expiring_30d: number;
  outdated_version: number;
  active_students?: number;
  adoption_rate?: number | null;
}

export interface AdminCurrentWaiverView {
  waiver_id: string;
  title: string;
  version: string;
  description?: string | null;
  effective_at?: string | null;
  last_edited_at?: string | null;
  signed_count?: number | null;
  total_count?: number | null;
  adoption_rate?: number | null;
}

export interface AdminWaiverStudentRow {
  waiver_id: string;
  signature_id?: string | null;
  student_id: string;
  student_name: string;
  parent_id: string;
  parent_name: string | null;
  parent_email: string | null;
  status: AdminWaiverStatus;
  template_id?: string | null;
  version: string | null;
  signed_at: string | null;
  method: string | null;
  expires_at: string | null;
  artifact_status?: string | null;
  share_status?: string | null;
}

export interface AdminWaiverList {
  summary: AdminWaiverSummary;
  current_waiver?: AdminCurrentWaiverView | null;
  waivers: AdminWaiverStudentRow[];
}

export type AdminWaiverTemplateStatus = "draft" | "active" | "superseded" | "retired";

export interface AdminWaiverTemplateManagementView {
  waiver_template_id: string;
  title: string;
  body: string;
  status: AdminWaiverTemplateStatus;
  version: string | null;
  content_hash: string | null;
  effective_at: string | null;
  published_at: string | null;
  assigned_to_registration: boolean;
  assigned_at: string | null;
  updated_at: string;
}

export interface AdminWaiverTemplateManagementList {
  templates: AdminWaiverTemplateManagementView[];
}

export interface AdminWaiverTemplateCreateRequest {
  title: string;
  body: string;
}

export interface AdminWaiverTemplateDetail {
  waiver_id: string;
  title: string;
  version: string;
  status: AdminWaiverTemplateStatus;
  body: string | null;
  content_hash: string | null;
  effective_at: string | null;
  assigned_to_registration: boolean;
  assigned_at: string | null;
  artifact_status: string;
  share_status: string;
  gap_note: string;
}

export interface AdminWaiverSignatureDetail {
  signature_id: string;
  student_name: string;
  parent_name: string | null;
  parent_email: string | null;
  signed_at: string;
  signer_name: string | null;
  signer_email: string | null;
  waiver_title: string | null;
  waiver_version: string | null;
  template_reference: string | null;
  content_hash: string | null;
  artifact_reference: string | null;
  share_link_reference: string | null;
  artifact_status: string;
  share_status: string;
  gap_note: string;
}

export interface AdminRegistrationRow {
  application_id: string;
  status: string;
  parent_email: string;
  parent_name: string | null;
  student_name: string | null;
  selected_session_id: string | null;
  waiver_required: boolean;
  waiver_satisfied: boolean;
  updated_at: string;
}

export interface AdminRegistrationList {
  registrations: AdminRegistrationRow[];
}

export interface AdminRegistrationDetail extends AdminRegistrationRow {
  parent_user_id: string;
  child_first_name: string;
  child_last_name: string;
  child_skill_level: string;
  payment_id: string | null;
  student_id: string | null;
  enrollment_id: string | null;
  waitlist_id: string | null;
  session_title: string | null;
  session_capacity: number | null;
  waiver_template_id: string | null;
  waiver_title: string | null;
  waiver_version: string | null;
}

export type AdminAttentionSeverity = "high" | "medium" | "low";
export type AdminAttentionKind =
  | "overdue_dues"
  | "pause_requests"
  | "scheduled_resume_blocked"
  | "billing_deferrals"
  | "waivers"
  | "session_pressure";

export interface AdminAttentionItem {
  attention_id: string;
  kind: AdminAttentionKind;
  title: string;
  detail: string;
  severity: AdminAttentionSeverity;
  href: string;
  count: number;
}

export interface AdminAttentionList {
  items: AdminAttentionItem[];
}

export interface BroadcastRequest {
  body: string;
  scope_type?: string;
  scope_label?: string | null;
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
  phone?: string | null;
}

export interface AdminUserDetail extends AdminUserView {
  roles: AdminUserRole[];
  linked_student_count: number;
  session_count: number;
  login_invite_sent_at?: string | null;
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
  attendance_rate: number | null;
  dues_status: "current" | "due" | "overdue";
}

export interface AdminStudentList {
  students: AdminStudentView[];
  next_cursor: string | null;
}

export interface ChangeAdminStudentParentRequest {
  parent_id: string;
  reason: string;
}

export interface AdminStudentParentSummaryView {
  parent_id: string;
  display_name: string;
  email: string;
  phone: string | null;
}

export interface AdminStudentParentChangeView {
  student_id: string;
  parent: AdminStudentParentSummaryView;
  previous_parent_id: string | null;
  warnings: string[];
  impact_counts: Record<string, number>;
}

export interface ListAdminStudentsParams {
  search?: string;
  status?: string;
  limit?: number;
  cursor?: string;
}

type QueryFunctionContextArg = {
  queryKey: readonly unknown[];
  signal?: AbortSignal;
};

export interface AdminPauseRequestView {
  pause_request_id: string;
  parent_id: string;
  parent_name: string | null;
  parent_email: string | null;
  enrollment_id: string;
  student_id: string | null;
  student_name: string | null;
  session_id: string | null;
  session_title: string | null;
  session_location: string | null;
  session_start_at: string | null;
  session_end_at: string | null;
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
  total_due_cents: number;
}

export interface DuesFollowupResponse {
  parents: DuesFollowupParentView[];
}

export interface SendDuesRemindersResponse {
  sent: number;
  blocked: boolean;
  reason: string | null;
  selected_parent_ids: string[];
  generated_invoice_artifacts: number;
}

export interface AdminAcademyView {
  academy_id: string;
  display_name: string;
  timezone: string;
  contact_email: string | null;
  contact_phone: string | null;
  hours_text: string | null;
  address: string | null;
  logo_url: string | null;
  brand_color: string | null;
  currency: string;
}

export type UpdateAdminAcademyRequest = Partial<{
  display_name: string | null;
  timezone: string | null;
  contact_email: string | null;
  contact_phone: string | null;
  hours_text: string | null;
  address: string | null;
  logo_url: string | null;
  brand_color: string | null;
  currency: string | null;
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
  coach_digest_enabled: boolean;
  coach_digest_hour: number;
}

export type UpdateAdminNotificationsRequest = Partial<AdminNotificationsView>;

export interface CoachDigestTestSendRequest {
  coach_id?: string | null;
  on_date?: string | null;
}

export interface CoachDigestTestSendResponse {
  status: "sent" | "skipped_empty" | "failed";
  coach_id: string;
  email: string | null;
  detail: string | null;
}

export interface CoachDigestLogEntryView {
  digest_id: string;
  coach_id: string;
  coach_email: string | null;
  digest_date: string;
  status: string;
  kind: string;
  sent_at: string | null;
  failed_reason: string | null;
  created_at: string | null;
}

export interface CoachDigestLogView {
  entries: CoachDigestLogEntryView[];
}

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

export function getAdminUser(userId: string): Promise<AdminUserDetail> {
  return apiFetch<AdminUserDetail>(`/admin/users/${encodeURIComponent(userId)}`, {
    method: "GET",
  });
}

export function updateAdminUser(
  userId: string,
  payload: Partial<{
    email: string;
    display_name: string;
    phone: string | null;
    status: string;
    reason: string;
  }>,
): Promise<AdminUserDetail> {
  return apiFetch<AdminUserDetail>(`/admin/users/${encodeURIComponent(userId)}`, {
    method: "PATCH",
    body: JSON.stringify(payload),
  });
}

export function listAdminSessionsByCoach(coachId: string): Promise<AdminSessionList> {
  return apiFetch<AdminSessionList>(
    `/admin/sessions?window=upcoming&coach_id=${encodeURIComponent(coachId)}`,
    { method: "GET" },
  );
}

function isQueryFunctionContext(params: ListAdminStudentsParams | QueryFunctionContextArg): params is QueryFunctionContextArg {
  return "queryKey" in params;
}

export function listAdminStudents(
  params: ListAdminStudentsParams | QueryFunctionContextArg = {},
): Promise<AdminStudentList> {
  const options = isQueryFunctionContext(params) ? {} : params;
  const q = new URLSearchParams();
  if (options.search) q.set("search", options.search);
  if (options.status) q.set("status", options.status);
  if (options.limit) q.set("limit", String(options.limit));
  if (options.cursor) q.set("cursor", options.cursor);
  const suffix = q.toString() ? `?${q.toString()}` : "";
  return apiFetch<AdminStudentList>(`/admin/students${suffix}`, { method: "GET" });
}

export function changeAdminStudentParent(
  studentId: string,
  payload: ChangeAdminStudentParentRequest,
): Promise<AdminStudentParentChangeView> {
  return apiFetch<AdminStudentParentChangeView>(
    `/admin/students/${encodeURIComponent(studentId)}/change-parent`,
    {
      method: "POST",
      body: JSON.stringify(payload),
    },
  );
}

export function addAdminUserRole(
  userId: string,
  role: AdminUserRole,
  reason = "Admin role change",
): Promise<AdminUserDetail> {
  return apiFetch<AdminUserDetail>(
    `/admin/users/${encodeURIComponent(userId)}/roles`,
    { method: "POST", body: JSON.stringify({ role, reason }) },
  );
}

export function removeAdminUserRole(
  userId: string,
  role: AdminUserRole,
  reason = "Admin role change",
): Promise<AdminUserDetail> {
  return apiFetch<AdminUserDetail>(
    `/admin/users/${encodeURIComponent(userId)}/roles/${role}?reason=${encodeURIComponent(reason)}`,
    { method: "DELETE" },
  );
}

export function sendLoginInvite(userId: string): Promise<{ sent_at: string }> {
  return apiFetch<{ sent_at: string }>(
    `/admin/users/${encodeURIComponent(userId)}/login-invite`,
    { method: "POST" },
  );
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

export function getAdminSession(sessionId: string): Promise<AdminSessionView> {
  return apiFetch<AdminSessionView>(`/admin/sessions/${encodeURIComponent(sessionId)}`, {
    method: "GET",
  });
}

export function createAdminSession(payload: CreateSessionRequest): Promise<AdminSessionView> {
  return apiFetch<AdminSessionView>("/admin/sessions", {
    method: "POST",
    body: JSON.stringify(payload),
  });
}

export function updateAdminSession(
  sessionId: string,
  payload: EditSessionRequest
): Promise<AdminSessionView> {
  return apiFetch<AdminSessionView>(`/admin/sessions/${encodeURIComponent(sessionId)}`, {
    method: "PATCH",
    body: JSON.stringify(payload),
  });
}

export function deleteAdminSession(sessionId: string): Promise<void> {
  return apiFetch<void>(`/admin/sessions/${sessionId}`, { method: "DELETE" });
}

export function listSessionOccurrences(
  sessionId: string
): Promise<AdminSessionOccurrenceList> {
  return apiFetch<AdminSessionOccurrenceList>(
    `/admin/sessions/${encodeURIComponent(sessionId)}/occurrences`,
    { method: "GET" }
  );
}

export function updateSessionOccurrenceCoach(
  occurrenceId: string,
  payload: UpdateSessionOccurrenceCoachRequest
): Promise<AdminSessionOccurrenceView> {
  return apiFetch<AdminSessionOccurrenceView>(
    `/admin/session-occurrences/${encodeURIComponent(occurrenceId)}/coach`,
    {
      method: "PATCH",
      body: JSON.stringify(payload),
    }
  );
}

export function updateSessionOccurrenceReplacement(
  occurrenceId: string,
  payload: UpdateOccurrenceReplacementRequest
): Promise<AdminSessionOccurrenceView> {
  return apiFetch<AdminSessionOccurrenceView>(
    `/admin/session-occurrences/${encodeURIComponent(occurrenceId)}/replacement`,
    {
      method: "PATCH",
      body: JSON.stringify(payload),
    }
  );
}

export function addSessionReplacement(
  sessionId: string,
  payload: AddSessionReplacementRequest
): Promise<AdminSessionOccurrenceView> {
  return apiFetch<AdminSessionOccurrenceView>(
    `/admin/sessions/${encodeURIComponent(sessionId)}/replacement`,
    {
      method: "PATCH",
      body: JSON.stringify(payload),
    }
  );
}

export function updateOccurrenceCoachAttendance(
  occurrenceId: string,
  payload: UpdateOccurrenceCoachAttendanceRequest
): Promise<AdminCoachAttendanceView> {
  return apiFetch<AdminCoachAttendanceView>(
    `/admin/session-occurrences/${encodeURIComponent(occurrenceId)}/coach-attendance`,
    {
      method: "PATCH",
      body: JSON.stringify(payload),
    }
  );
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

export function withdrawEnrollment(
  enrollmentId: string,
  payload: WithdrawEnrollmentRequest
): Promise<void> {
  return apiFetch<void>(`/admin/enrollments/${enrollmentId}/withdraw`, {
    method: "POST",
    body: JSON.stringify(payload),
  });
}

export function deleteEnrollment(
  enrollmentId: string,
  payload: RemoveEnrollmentRequest
): Promise<void> {
  return apiFetch<void>(`/admin/enrollments/${enrollmentId}`, {
    method: "DELETE",
    body: JSON.stringify(payload),
  });
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

export function pauseEnrollment(
  enrollmentId: string,
  payload: PauseEnrollmentRequest
): Promise<void> {
  return apiFetch<void>(`/admin/enrollments/${enrollmentId}/pause`, {
    method: "POST",
    body: JSON.stringify(payload),
  });
}

export function resumeEnrollment(enrollmentId: string): Promise<void> {
  return apiFetch<void>(`/admin/enrollments/${enrollmentId}/resume`, { method: "POST" });
}

export function listEnrollmentEvents(enrollmentId: string): Promise<EnrollmentEventsResponse> {
  return apiFetch<EnrollmentEventsResponse>(`/admin/enrollments/${enrollmentId}/events`, {
    method: "GET",
  });
}

// ---------------------------------------------------------------------------
// Waitlist
// ---------------------------------------------------------------------------

export function listSessionWaitlist(sessionId: string): Promise<AdminWaitlistList> {
  return apiFetch<AdminWaitlistList>(`/admin/sessions/${sessionId}/waitlist`, { method: "GET" });
}

export function listGlobalWaitlist(): Promise<AdminGlobalWaitlistList> {
  return apiFetch<AdminGlobalWaitlistList>("/admin/waitlist", { method: "GET" });
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

export function listAdminPayments(filters?: AdminPaymentListFilters): Promise<AdminPaymentList> {
  const params = new URLSearchParams();
  if (filters) {
    for (const [key, value] of Object.entries(filters)) {
      if (value !== undefined && value !== null && `${value}` !== "") {
        params.set(key, `${value}`);
      }
    }
  }
  const query = params.toString();
  return apiFetch<AdminPaymentList>(`/admin/payments${query ? `?${query}` : ""}`, {
    method: "GET",
  });
}

export function getAdminPaymentFeed(limit = 20): Promise<AdminPaymentFeedResponse> {
  return apiFetch<AdminPaymentFeedResponse>(`/admin/payments/feed?limit=${limit}`, {
    method: "GET",
  });
}

export function getAdminLastPaymentByFamily(): Promise<AdminFamilyLastPaymentsResponse> {
  return apiFetch<AdminFamilyLastPaymentsResponse>("/admin/payments/last-by-family", {
    method: "GET",
  });
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

export function reconcileStripeBilling(
  payload: ReconcileStripeBillingRequest,
): Promise<ReconcileStripeBillingResponse> {
  return apiFetch<ReconcileStripeBillingResponse>("/admin/billing/reconcile", {
    method: "POST",
    body: JSON.stringify(payload),
  });
}

export function getBillingReconciliationReport(params: {
  stripe_invoice_id?: string | null;
  payment_intent_id?: string | null;
}): Promise<BillingReconciliationReport> {
  const query = new URLSearchParams();
  if (params.stripe_invoice_id) query.set("stripe_invoice_id", params.stripe_invoice_id);
  if (params.payment_intent_id) query.set("payment_intent_id", params.payment_intent_id);
  return apiFetch<BillingReconciliationReport>(`/admin/billing/reconciliation?${query.toString()}`, {
    method: "GET",
  });
}

export function listBillingWebhookEvents(params: {
  status?: "failed" | "quarantined" | string | null;
  limit?: number;
} = {}): Promise<BillingWebhookQueue> {
  const query = new URLSearchParams();
  if (params.status) query.set("status", params.status);
  if (params.limit) query.set("limit", String(params.limit));
  const suffix = query.toString() ? `?${query.toString()}` : "";
  return apiFetch<BillingWebhookQueue>(`/admin/billing/webhooks${suffix}`, { method: "GET" });
}

// --- Billing Health (#235) ------------------------------------------------- //
export interface ReconciliationRun {
  run_id: string;
  started_at: string | null;
  finished_at: string | null;
  scanned: number;
  repaired: number;
  skipped: number;
  quarantined: number;
  failed: number;
  errors: unknown[];
  notes: string[];
}

export interface ReconciliationRunsResponse {
  runs: ReconciliationRun[];
}

export interface FailedPaymentRow {
  invoice_id: string;
  parent_id: string;
  parent_name: string | null;
  period: string;
  total_cents: number;
  balance_due_cents: number;
  currency: string;
  latest_attempt_at: string | null;
  latest_decline_code: string | null;
  attempt_count: number;
}

export interface FailedPaymentsResponse {
  rows: FailedPaymentRow[];
}

export interface DunningRow {
  invoice_id: string;
  parent_id: string;
  parent_name: string | null;
  period: string;
  status: string;
  attempt_count: number;
  next_attempt_at: string | null;
  last_attempt_at: string | null;
  last_failure_code: string | null;
  terminal_at: string | null;
  autopay_disable_status: string | null;
  autopay_disable_error: string | null;
  autopay_disabled_at: string | null;
  balance_due_cents: number;
  currency: string;
}

export interface DunningResponse {
  rows: DunningRow[];
}

export interface BillingPaymentAttempt {
  attempt_id: string;
  status: string;
  amount_cents: number;
  currency: string;
  stripe_payment_intent_id: string | null;
  failure_code: string | null;
  failure_message: string | null;
  created_at: string | null;
}

export interface InvoiceAttemptsResponse {
  attempts: BillingPaymentAttempt[];
}

export function fetchReconciliationRuns(): Promise<ReconciliationRunsResponse> {
  return apiFetch<ReconciliationRunsResponse>("/admin/billing/reconciliation-runs", {
    method: "GET",
  });
}

export function triggerReconciliation(): Promise<ReconciliationRun> {
  return apiFetch<ReconciliationRun>("/admin/billing/reconcile-now", { method: "POST" });
}

export function fetchFailedPaymentAttempts(): Promise<FailedPaymentsResponse> {
  return apiFetch<FailedPaymentsResponse>("/admin/billing/failed-payment-attempts", {
    method: "GET",
  });
}

export function fetchDunningFailures(): Promise<DunningResponse> {
  return apiFetch<DunningResponse>("/admin/billing/dunning", {
    method: "GET",
  });
}

export function fetchInvoiceAttempts(invoiceId: string): Promise<InvoiceAttemptsResponse> {
  return apiFetch<InvoiceAttemptsResponse>(
    `/admin/billing/invoices/${encodeURIComponent(invoiceId)}/attempts`,
    { method: "GET" },
  );
}

export function replayWebhookEvent(
  eventId: string,
): Promise<{ replayed: boolean; event_id: string }> {
  return apiFetch<{ replayed: boolean; event_id: string }>(
    `/admin/billing/webhook-events/${encodeURIComponent(eventId)}/replay`,
    { method: "POST" },
  );
}

// --- Legacy invoice ↔ Stripe charge review queue (#242 WI-3) --------------- //
export interface LegacyMatchCandidate {
  stripe_charge_id: string;
  stripe_payment_intent_id: string | null;
  amount_cents: number;
  currency: string;
  created_at: string | null;
  description: string | null;
  confidence: "high" | "medium" | string;
}

export interface LegacyMatchRow {
  invoice_id: string;
  parent_id: string;
  parent_name: string | null;
  period: string;
  status: string;
  total_cents: number;
  balance_due_cents: number;
  currency: string;
  due_date: string | null;
  created_at: string | null;
  stripe_invoice_id: string | null;
  stripe_customer_id: string | null;
  candidates: LegacyMatchCandidate[];
}

export interface LegacyMatchQueueResponse {
  rows: LegacyMatchRow[];
}

export interface ConfirmLegacyMatchRequest {
  invoice_id: string;
  stripe_charge_id: string;
  amount_cents: number;
  stripe_payment_intent_id?: string | null;
  paid_at?: string | null;
}

export interface ConfirmLegacyMatchResult {
  invoice_id: string;
  payment_id: string;
  invoice_status: string;
  balance_due_cents: number;
}

export function fetchLegacyMatchQueue(): Promise<LegacyMatchQueueResponse> {
  return apiFetch<LegacyMatchQueueResponse>("/admin/billing/legacy-match-queue", {
    method: "GET",
  });
}

export function confirmLegacyMatch(
  payload: ConfirmLegacyMatchRequest,
): Promise<ConfirmLegacyMatchResult> {
  return apiFetch<ConfirmLegacyMatchResult>("/admin/billing/legacy-match/confirm", {
    method: "POST",
    body: JSON.stringify(payload),
  });
}

export function listBillingProducts(): Promise<AdminBillingProductList> {
  return apiFetch<AdminBillingProductList>("/admin/billing/products", {
    method: "GET",
  });
}

export function createBillingProduct(
  payload: CreateBillingProductRequest,
): Promise<AdminBillingProductView> {
  return apiFetch<AdminBillingProductView>("/admin/billing/products", {
    method: "POST",
    body: JSON.stringify(payload),
  });
}

export function updateBillingProduct(
  productId: string,
  payload: UpdateBillingProductRequest,
): Promise<AdminBillingProductView> {
  return apiFetch<AdminBillingProductView>(
    `/admin/billing/products/${encodeURIComponent(productId)}`,
    {
      method: "PATCH",
      body: JSON.stringify(payload),
    },
  );
}

export function deleteBillingProduct(productId: string): Promise<void> {
  return apiFetch<void>(`/admin/billing/products/${encodeURIComponent(productId)}`, {
    method: "DELETE",
  });
}

export function getAdminInvoiceDetail(invoiceId: string): Promise<AdminInvoiceDetail> {
  return apiFetch<AdminInvoiceDetail>(
    `/admin/billing/invoices/${encodeURIComponent(invoiceId)}`,
    { method: "GET" },
  );
}

export function addAdminInvoiceLine(
  invoiceId: string,
  payload: AddInvoiceLineRequest,
): Promise<InvoiceLineMutationResponse> {
  return apiFetch<InvoiceLineMutationResponse>(
    `/admin/billing/invoices/${encodeURIComponent(invoiceId)}/lines`,
    {
      method: "POST",
      body: JSON.stringify(payload),
    },
  );
}

export function applyAdminInvoiceAdjustment(
  invoiceId: string,
  payload: ApplyInvoiceAdjustmentRequest,
): Promise<InvoiceLineMutationResponse> {
  return apiFetch<InvoiceLineMutationResponse>(
    `/admin/billing/invoices/${encodeURIComponent(invoiceId)}/adjustments`,
    {
      method: "POST",
      body: JSON.stringify(payload),
    },
  );
}

export function deleteAdminInvoiceLine(invoiceId: string, lineId: string): Promise<void> {
  return apiFetch<void>(
    `/admin/billing/invoices/${encodeURIComponent(invoiceId)}/lines/${encodeURIComponent(lineId)}`,
    { method: "DELETE" },
  );
}

export function sendAdminInvoice(invoiceId: string): Promise<SendInvoiceResponse> {
  return apiFetch<SendInvoiceResponse>(
    `/admin/billing/invoices/${encodeURIComponent(invoiceId)}/send`,
    { method: "POST" },
  );
}

export function chargeAdminInvoiceAutopay(
  invoiceId: string,
): Promise<ChargeAutopayResponse> {
  return apiFetch<ChargeAutopayResponse>(
    `/admin/billing/invoices/${encodeURIComponent(invoiceId)}/charge-autopay`,
    { method: "POST" },
  );
}

export function recordAdminInvoicePayment(
  invoiceId: string,
  payload: RecordManualPaymentRequest,
): Promise<RecordManualPaymentResponse> {
  return apiFetch<RecordManualPaymentResponse>(
    `/admin/billing/invoices/${encodeURIComponent(invoiceId)}/record-payment`,
    {
      method: "POST",
      body: JSON.stringify(payload),
    },
  );
}

export function refundAdminInvoice(
  invoiceId: string,
  payload: InvoiceRefundRequest,
): Promise<InvoiceRefundResponse> {
  return apiFetch<InvoiceRefundResponse>(
    `/admin/billing/invoices/${encodeURIComponent(invoiceId)}/refund`,
    {
      method: "POST",
      body: JSON.stringify(payload),
    },
  );
}

export function voidAdminInvoice(
  invoiceId: string,
  payload: VoidInvoiceRequest,
): Promise<VoidInvoiceResponse> {
  return apiFetch<VoidInvoiceResponse>(
    `/admin/billing/invoices/${encodeURIComponent(invoiceId)}/void`,
    { method: "POST", body: JSON.stringify(payload) },
  );
}

export function generateAdminInvoiceArtifact(
  invoiceId: string,
  artifactType: "invoice_pdf" | "receipt",
): Promise<GenerateInvoiceArtifactResponse> {
  return apiFetch<GenerateInvoiceArtifactResponse>(
    `/admin/billing/invoices/${encodeURIComponent(invoiceId)}/artifacts`,
    {
      method: "POST",
      body: JSON.stringify({ artifact_type: artifactType }),
    },
  );
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

export function listCoachPayRates(coachId: string): Promise<AdminCoachPayRateList> {
  return apiFetch<AdminCoachPayRateList>(
    `/admin/coaches/${encodeURIComponent(coachId)}/pay-rates`,
    { method: "GET" }
  );
}

export function setCoachPayRate(
  coachId: string,
  payload: SetCoachPayRateRequest
): Promise<AdminCoachPayRateView> {
  return apiFetch<AdminCoachPayRateView>(
    `/admin/coaches/${encodeURIComponent(coachId)}/pay-rates`,
    {
      method: "POST",
      body: JSON.stringify(payload),
    }
  );
}

export function repairCoachPayRateWindow(
  coachId: string,
  payload: RepairCoachPayRateWindowRequest
): Promise<AdminCoachPayRateView> {
  return apiFetch<AdminCoachPayRateView>(
    `/admin/coaches/${encodeURIComponent(coachId)}/pay-rates/repair`,
    {
      method: "POST",
      body: JSON.stringify(payload),
    }
  );
}

export function createExpense(payload: CreateExpenseRequest): Promise<AdminExpenseView> {
  return apiFetch<AdminExpenseView>("/admin/finance/expenses", {
    method: "POST",
    body: JSON.stringify(payload),
  });
}

export function updateExpense(
  expenseId: string,
  payload: EditExpenseRequest
): Promise<AdminExpenseView> {
  return apiFetch<AdminExpenseView>(`/admin/finance/expenses/${encodeURIComponent(expenseId)}`, {
    method: "PATCH",
    body: JSON.stringify(payload),
  });
}

export function deleteExpense(expenseId: string, payload: { reason: string }): Promise<void> {
  return apiFetch<void>(`/admin/finance/expenses/${encodeURIComponent(expenseId)}`, {
    method: "DELETE",
    body: JSON.stringify(payload),
  });
}

export function getRevenue(): Promise<AdminRevenueResponse> {
  return apiFetch<AdminRevenueResponse>("/admin/finance/revenue", { method: "GET" });
}

export function getAdminReportKpis(): Promise<AdminReportsKpiResponse> {
  return apiFetch<AdminReportsKpiResponse>("/admin/reports/kpis", { method: "GET" });
}

export interface AdminProjectedIncomeSessionRow {
  session_id: string;
  title: string;
  monthly_fee_cents: number;
  enrollment_count: number;
  expected_cents: number;
}

export interface AdminProjectedIncomeResponse {
  period: string;
  total_cents: number;
  autopay_cents: number;
  manual_cents: number;
  enrollment_count: number;
  autopay_enrollment_count: number;
  manual_enrollment_count: number;
  by_session: AdminProjectedIncomeSessionRow[];
  empty: boolean;
}

export function getAdminProjectedIncome(period: string): Promise<AdminProjectedIncomeResponse> {
  return apiFetch<AdminProjectedIncomeResponse>(
    `/admin/reports/projected-income?period=${encodeURIComponent(period)}`,
    { method: "GET" },
  );
}

export function getAdminReportsDashboard(period: string): Promise<AdminReportsDashboardResponse> {
  return apiFetch<AdminReportsDashboardResponse>(
    `/admin/reports/dashboard?period=${encodeURIComponent(period)}`,
    { method: "GET" },
  );
}

export function getAdminSessionEconomics(period: string): Promise<AdminSessionEconomicsResponse> {
  return apiFetch<AdminSessionEconomicsResponse>(
    `/admin/reports/session-economics?period=${encodeURIComponent(period)}`,
    { method: "GET" },
  );
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

export interface CampaignAudiencePayload {
  type: "academy" | "session";
  role?: "parent" | "coach";
  session_id?: string;
}

export interface SendEmailCampaignRequest {
  subject: string;
  body: string;
  audience: CampaignAudiencePayload;
}

export interface SendEmailCampaignResponse {
  campaign_id: string;
  total_recipients: number;
  sent_count: number;
  failed_count: number;
}

export function sendEmailCampaign(
  payload: SendEmailCampaignRequest,
): Promise<SendEmailCampaignResponse> {
  return apiFetch<SendEmailCampaignResponse>("/admin/campaigns", {
    method: "POST",
    body: JSON.stringify(payload),
  });
}

export function listAdminWaivers(): Promise<AdminWaiverList> {
  return apiFetch<AdminWaiverList>("/admin/waivers", { method: "GET" });
}

export function listAdminWaiverTemplates(): Promise<AdminWaiverTemplateManagementList> {
  return apiFetch<AdminWaiverTemplateManagementList>("/admin/waivers/templates", {
    method: "GET",
  });
}

export function createAdminWaiverTemplate(
  payload: AdminWaiverTemplateCreateRequest,
): Promise<AdminWaiverTemplateManagementView> {
  return apiFetch<AdminWaiverTemplateManagementView>("/admin/waivers/templates", {
    method: "POST",
    body: JSON.stringify(payload),
  });
}

export function publishAdminWaiverTemplate(
  waiverTemplateId: string,
): Promise<AdminWaiverTemplateManagementView> {
  return apiFetch<AdminWaiverTemplateManagementView>(
    `/admin/waivers/templates/${encodeURIComponent(waiverTemplateId)}/publish`,
    { method: "POST" },
  );
}

export function assignAdminWaiverTemplateToRegistration(
  waiverTemplateId: string,
): Promise<AdminWaiverTemplateManagementView> {
  return apiFetch<AdminWaiverTemplateManagementView>(
    `/admin/waivers/templates/${encodeURIComponent(waiverTemplateId)}/assign-registration`,
    { method: "POST" },
  );
}

export function getAdminWaiverTemplate(waiverId: string): Promise<AdminWaiverTemplateDetail> {
  return apiFetch<AdminWaiverTemplateDetail>(`/admin/waivers/${encodeURIComponent(waiverId)}`, {
    method: "GET",
  });
}

export function getAdminWaiverSignature(signatureId: string): Promise<AdminWaiverSignatureDetail> {
  return apiFetch<AdminWaiverSignatureDetail>(
    `/admin/waivers/signatures/${encodeURIComponent(signatureId)}`,
    { method: "GET" },
  );
}

export function listAdminRegistrations(): Promise<AdminRegistrationList> {
  return apiFetch<AdminRegistrationList>("/admin/registrations", { method: "GET" });
}

export function getAdminRegistration(applicationId: string): Promise<AdminRegistrationDetail> {
  return apiFetch<AdminRegistrationDetail>(
    `/admin/registrations/${encodeURIComponent(applicationId)}`,
    { method: "GET" },
  );
}

export function approveAdminRegistration(
  applicationId: string,
  payload: { session_id?: string | null; waiver_override_reason?: string | null } = {},
): Promise<AdminRegistrationDetail> {
  return apiFetch<AdminRegistrationDetail>(
    `/admin/registrations/${encodeURIComponent(applicationId)}/approve`,
    { method: "POST", body: JSON.stringify(payload) },
  );
}

export function waitlistAdminRegistration(
  applicationId: string,
  payload: { session_id?: string | null; reason?: string | null } = {},
): Promise<AdminRegistrationDetail> {
  return apiFetch<AdminRegistrationDetail>(
    `/admin/registrations/${encodeURIComponent(applicationId)}/waitlist`,
    { method: "POST", body: JSON.stringify(payload) },
  );
}

export function rejectAdminRegistration(
  applicationId: string,
  payload: { reason: string },
): Promise<AdminRegistrationDetail> {
  return apiFetch<AdminRegistrationDetail>(
    `/admin/registrations/${encodeURIComponent(applicationId)}/reject`,
    { method: "POST", body: JSON.stringify(payload) },
  );
}

export function listAdminAttention(): Promise<AdminAttentionList> {
  return apiFetch<AdminAttentionList>("/admin/dashboard/attention", { method: "GET" });
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

// ---------------------------------------------------------------------------
// Self-service policy + request queues (absences, makeups, trials, cancellations)
// ---------------------------------------------------------------------------

export interface SelfServicePolicyView {
  absence_notice_min_hours: number;
  makeup_expiry_days: number;
  makeup_requires_notice: boolean;
  cancellation_minimum_notice_days: number;
  cancellation_fee_cents: number;
  cancellation_effective_timing: "immediate" | "end_of_period";
}

export type UpdateSelfServicePolicyRequest = SelfServicePolicyView;

export interface AbsenceNoticeAdminRow {
  notice_id: string;
  student_id: string;
  occurrence_id: string;
  session_id: string;
  submitted_by: string;
  submitted_at: string;
  notice_window_met: boolean;
  student_full_name: string | null;
}

export interface AbsencesAdminResponse {
  absences: AbsenceNoticeAdminRow[];
}

export type SelfServiceRequestStatus = "pending" | "approved" | "denied" | "expired" | "converted";

export interface MakeupRequestAdminRow {
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
  student_full_name: string | null;
}

export interface MakeupRequestsAdminResponse {
  makeups: MakeupRequestAdminRow[];
}

export interface ApproveMakeupRequestBody {
  target_occurrence_id: string;
}

export interface DenyMakeupRequestBody {
  reason: string;
}

export interface TrialRequestAdminRow {
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

export interface TrialRequestsAdminResponse {
  trials: TrialRequestAdminRow[];
}

export interface ApproveTrialRequestBody {
  occurrence_id: string;
}

export interface DenyTrialRequestBody {
  reason: string;
}

export interface SelfCancellationAdminRow {
  enrollment_id: string;
  student_id: string;
  session_id: string;
  cancellation_reason: string | null;
  cancellation_policy_snapshot: Record<string, unknown> | null;
  cancelled_at: string | null;
  student_full_name: string | null;
  session_title: string | null;
}

export interface SelfCancellationsAdminResponse {
  cancellations: SelfCancellationAdminRow[];
}

export function getSelfServicePolicy(): Promise<SelfServicePolicyView> {
  return apiFetch<SelfServicePolicyView>("/admin/self-service/policy", { method: "GET" });
}

export function updateSelfServicePolicy(
  payload: UpdateSelfServicePolicyRequest,
): Promise<SelfServicePolicyView> {
  return apiFetch<SelfServicePolicyView>("/admin/self-service/policy", {
    method: "PUT",
    body: JSON.stringify(payload),
  });
}

export function listAdminAbsences(): Promise<AbsencesAdminResponse> {
  return apiFetch<AbsencesAdminResponse>("/admin/self-service/absences", { method: "GET" });
}

export function listAdminMakeups(status?: string): Promise<MakeupRequestsAdminResponse> {
  const q = status ? `?status=${encodeURIComponent(status)}` : "";
  return apiFetch<MakeupRequestsAdminResponse>(`/admin/self-service/makeups${q}`, {
    method: "GET",
  });
}

export function approveMakeup(
  requestId: string,
  payload: ApproveMakeupRequestBody,
): Promise<MakeupRequestAdminRow> {
  return apiFetch<MakeupRequestAdminRow>(
    `/admin/self-service/makeups/${encodeURIComponent(requestId)}/approve`,
    { method: "POST", body: JSON.stringify(payload) },
  );
}

export function denyMakeup(
  requestId: string,
  payload: DenyMakeupRequestBody,
): Promise<MakeupRequestAdminRow> {
  return apiFetch<MakeupRequestAdminRow>(
    `/admin/self-service/makeups/${encodeURIComponent(requestId)}/deny`,
    { method: "POST", body: JSON.stringify(payload) },
  );
}

export function listAdminTrials(status?: string): Promise<TrialRequestsAdminResponse> {
  const q = status ? `?status=${encodeURIComponent(status)}` : "";
  return apiFetch<TrialRequestsAdminResponse>(`/admin/self-service/trials${q}`, {
    method: "GET",
  });
}

export function approveTrial(
  requestId: string,
  payload: ApproveTrialRequestBody,
): Promise<TrialRequestAdminRow> {
  return apiFetch<TrialRequestAdminRow>(
    `/admin/self-service/trials/${encodeURIComponent(requestId)}/approve`,
    { method: "POST", body: JSON.stringify(payload) },
  );
}

export function denyTrial(
  requestId: string,
  payload: DenyTrialRequestBody,
): Promise<TrialRequestAdminRow> {
  return apiFetch<TrialRequestAdminRow>(
    `/admin/self-service/trials/${encodeURIComponent(requestId)}/deny`,
    { method: "POST", body: JSON.stringify(payload) },
  );
}

export function listAdminCancellations(): Promise<SelfCancellationsAdminResponse> {
  return apiFetch<SelfCancellationsAdminResponse>("/admin/self-service/cancellations", {
    method: "GET",
  });
}

export function listAuditLogs(): Promise<AdminAuditLogList> {
  return apiFetch<AdminAuditLogList>("/admin/audit-logs", { method: "GET" });
}

export function listDuesFollowup(): Promise<DuesFollowupResponse> {
  return apiFetch<DuesFollowupResponse>("/admin/dues-followup", { method: "GET" });
}

export function sendDuesReminders(payload: { parent_ids?: string[] } = {}): Promise<SendDuesRemindersResponse> {
  return apiFetch<SendDuesRemindersResponse>("/admin/dues-reminders", {
    method: "POST",
    body: JSON.stringify(payload),
  });
}

export function exportAdminReportCsv(reportName: string, period?: string): Promise<string> {
  const query = period ? `?period=${encodeURIComponent(period)}` : "";
  return apiFetch<string>(`/admin/reports/${encodeURIComponent(reportName)}.csv${query}`, {
    method: "GET",
  });
}

export interface AdminRefundRow {
  refund_at: string | null;
  invoice_id: string | null;
  invoice_number: string | null;
  payment_id: string | null;
  parent_id: string | null;
  student_id: string | null;
  amount_cents: number;
  reason: string | null;
  actor_id: string | null;
}

export interface AdminCreditRow {
  credit_id: string;
  created_at: string | null;
  parent_id: string | null;
  student_id: string | null;
  invoice_id: string | null;
  type: string | null;
  status: string | null;
  amount_cents: number;
  remaining_amount_cents: number;
  reason: string | null;
}

export interface AdminRefundsReportResponse {
  period: string;
  total_refunded_cents: number;
  refund_count: number;
  refunds: AdminRefundRow[];
  total_credit_cents: number;
  credit_count: number;
  credits: AdminCreditRow[];
}

export interface AdminRevenueCategoryRow {
  category: string;
  category_label: string | null;
  amount_cents: number;
}

export interface AdminRevenueByCategoryResponse {
  period: string;
  total_allocated_cents: number;
  unapplied_cents: number;
  rows: AdminRevenueCategoryRow[];
}

export interface AdminDepositSlipMethodRow {
  method: string;
  amount_cents: number;
  count: number;
}

export interface AdminDepositSlipDayRow {
  date: string;
  total_cents: number;
  count: number;
  methods: AdminDepositSlipMethodRow[];
}

export interface AdminDepositSlipResponse {
  period: string;
  total_cents: number;
  count: number;
  days: AdminDepositSlipDayRow[];
}

export function getAdminRefundsReport(period: string): Promise<AdminRefundsReportResponse> {
  return apiFetch<AdminRefundsReportResponse>(
    `/admin/reports/refunds?period=${encodeURIComponent(period)}`,
    { method: "GET" },
  );
}

export function getAdminRevenueByCategory(
  period: string,
): Promise<AdminRevenueByCategoryResponse> {
  return apiFetch<AdminRevenueByCategoryResponse>(
    `/admin/reports/revenue-by-category?period=${encodeURIComponent(period)}`,
    { method: "GET" },
  );
}

export function getAdminDepositSlip(period: string): Promise<AdminDepositSlipResponse> {
  return apiFetch<AdminDepositSlipResponse>(
    `/admin/reports/deposit-slip?period=${encodeURIComponent(period)}`,
    { method: "GET" },
  );
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

export function sendCoachDigestTest(
  payload: CoachDigestTestSendRequest
): Promise<CoachDigestTestSendResponse> {
  return apiFetch<CoachDigestTestSendResponse>("/admin/comms/digests/test-send", {
    method: "POST",
    body: JSON.stringify(payload),
  });
}

export function getCoachDigestLog(limit = 20): Promise<CoachDigestLogView> {
  return apiFetch<CoachDigestLogView>(`/admin/comms/digests/log?limit=${limit}`, {
    method: "GET",
  });
}

export function getAdminGateway(): Promise<AdminGatewayView> {
  return apiFetch<AdminGatewayView>("/admin/academy/gateway", { method: "GET" });
}

export interface AdminGatewayConnectLinkView {
  url: string;
}

export function startStripeConnect(): Promise<AdminGatewayConnectLinkView> {
  return apiFetch<AdminGatewayConnectLinkView>(
    "/admin/academy/gateway/stripe/connect-link",
    { method: "POST" },
  );
}

export function disconnectStripe(): Promise<void> {
  return apiFetch<void>("/admin/academy/gateway/stripe/connect", { method: "DELETE" });
}

export interface CreateAdminUserRequest {
  role: AdminUserRole;
  display_name: string;
  email: string;
  phone: string | null;
  reason: string;
}

export function createAdminUser(payload: CreateAdminUserRequest): Promise<AdminUserDetail> {
  return apiFetch<AdminUserDetail>("/admin/users", {
    method: "POST",
    body: JSON.stringify(payload),
  });
}
