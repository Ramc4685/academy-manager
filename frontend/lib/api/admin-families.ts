/**
 * Admin Family billing page — `GET /admin/families/{parentId}/billing` and
 * `POST /admin/families/{parentId}/autopay/pause`.
 * Spec: docs/superpowers/specs/2026-09-05-family-billing-design.md §3.2, §5.
 * Kept out of `admin.ts` so the family types stay in one file.
 */
import { apiFetch } from "./client";

export type AutopayState = "on" | "off" | "partial" | "needs_consent";
export type RegistrationState = "registered" | "invited" | "not_invited";
export type FamilyAction =
  | "send_invite"
  | "autopay_on"
  | "autopay_off"
  | "send_invoice"
  | "record_payment";
export type InvoiceAction =
  | "send"
  | "record_payment"
  | "charge_card"
  | "void"
  | "refund"
  | "discount_once";
export type TimelineKind = "money" | "admin" | "lifecycle" | "comms";

export interface FamilyAutopay {
  state: AutopayState;
  active_count: number;
  total_count: number;
  card_last4: string | null;
  card_label: string | null;
  next_charge_on: string | null;
  next_charge_invoice_id: string | null;
  last_failure: { code: string | null; at: string | null } | null;
}

export interface FamilyLastPayment {
  amount_cents: number;
  method: string | null;
  paid_at: string | null;
  invoice_ids: string[];
}

export interface FamilyRegistration {
  state: RegistrationState;
  card_on_file: boolean;
  last_invited_at: string | null;
}

/** #778: what the provider knows about this family's address. */
export interface FamilyEmailDelivery {
  undeliverable: boolean;
  since: string | null;
  reason: "hard_bounce" | "complaint" | "manual" | string | null;
  email: string | null;
}

export interface FamilyHeader {
  balance_cents: number;
  open_invoice_count: number;
  available_credit_cents: number;
  last_payment: FamilyLastPayment | null;
  autopay: FamilyAutopay;
  registration: FamilyRegistration;
  email_delivery?: FamilyEmailDelivery;
  enrollment_counts: { active: number; paused: number; cancelled: number };
}

export interface FamilyEnrollment {
  enrollment_id: string;
  session_id: string | null;
  session_title: string | null;
  schedule: string | null;
  status: string;
  monthly_price_cents: number | null;
  override_price_cents: number | null;
  autopay_status: string | null;
  recurring_discount: Record<string, unknown> | null;
  resume_on: string | null;
  actions: "recurring_discount"[];
}

export interface FamilyStudent {
  student_id: string;
  name: string;
  status: string | null;
  enrollments: FamilyEnrollment[];
}

export interface FamilyInvoiceDelivery {
  status: string;
  last_sent_at: string | null;
  kind: "invoice" | "autopay_notice";
}

export interface FamilyInvoiceAllocation {
  payment_id: string;
  amount_cents: number;
  method: string | null;
  paid_at: string | null;
  stripe_payment_intent_id: string | null;
}

export interface FamilyInvoiceCredit {
  credit_id: string;
  amount_cents: number;
}

export interface FamilyInvoice {
  invoice_id: string;
  invoice_number: string | null;
  period: string;
  student_id: string | null;
  student_name: string | null;
  enrollment_id: string | null;
  status: string;
  total_cents: number;
  paid_cents: number;
  balance_due_cents: number;
  due_date: string | null;
  created_at: string | null;
  paid_at: string | null;
  voided_at: string | null;
  void_reason: string | null;
  settlement_unlinked: boolean;
  delivery: FamilyInvoiceDelivery;
  allocations: FamilyInvoiceAllocation[];
  credits: FamilyInvoiceCredit[];
  chargeable: boolean;
  actions: InvoiceAction[];
}

export interface FamilyTimelineEntry {
  at: string;
  kind: TimelineKind;
  code: string;
  summary: string;
  invoice_id: string | null;
  invoice_ids: string[];
  enrollment_id: string | null;
  student_name: string | null;
  actor_id: string | null;
  reason: string | null;
  amount_cents: number | null;
  muted: boolean;
}

export interface FamilyParent {
  parent_id: string;
  name: string | null;
  email: string | null;
  phone: string | null;
}

export interface AdminFamilyBillingView {
  generated_at: string;
  timezone: string;
  today: string;
  parent: FamilyParent;
  header: FamilyHeader;
  students: FamilyStudent[];
  invoices: FamilyInvoice[];
  timeline: FamilyTimelineEntry[];
  actions: FamilyAction[];
  warnings: string[];
}

export function fetchAdminFamilyBilling(parentId: string): Promise<AdminFamilyBillingView> {
  return apiFetch<AdminFamilyBillingView>(
    `/admin/families/${encodeURIComponent(parentId)}/billing`,
  );
}

export interface PauseFamilyAutopayPayload {
  reason: string;
  request_id: string;
}

export interface PauseFamilyAutopayResponse {
  paused_count: number;
  active_count_before: number;
  warnings: string[];
}

export function pauseFamilyAutopay(
  parentId: string,
  payload: PauseFamilyAutopayPayload,
): Promise<PauseFamilyAutopayResponse> {
  return apiFetch<PauseFamilyAutopayResponse>(
    `/admin/families/${encodeURIComponent(parentId)}/autopay/pause`,
    { method: "POST", body: JSON.stringify(payload) },
  );
}

// ---------------------------------------------------------------------------
// People CRM family index — `GET /admin/families` and `/admin/families/summary`.
// Spec: docs/design/people-crm/engineering-spec.md §3.2. Shapes mirror
// backend/v2/interfaces/admin/family_index_views.py exactly.
// ---------------------------------------------------------------------------

export type FamilyStage =
  | "pending_cancel"
  | "active"
  | "at_risk"
  | "on_hold"
  | "paused"
  | "trial"
  | "never_enrolled"
  | "left";

export type FamilyScope = "active" | "leaving" | "left";
export type FamilyIndexSort = "name" | "stage" | "balance" | "children";

export interface FamilyIndexClass {
  session_id: string;
  title: string;
}

export interface FamilyIndexChild {
  student_id: string;
  name: string;
  lifecycle: FamilyStage;
  lifecycle_as_of: string | null;
  classes: FamilyIndexClass[];
  /** The search matched this child: the child is the result row (spec §3.2). */
  matched: boolean;
}

export interface FamilyIndexMoney {
  balance_cents: number;
  open_invoice_count: number;
  overdue_invoice_count: number;
  overdue_cents: number;
  oldest_overdue_due_on: string | null;
  last_failed_payment_at: string | null;
}

export interface FamilyIndexRow {
  /** The id `/admin/families/{family_id}` opens. */
  family_id: string;
  parent_name: string | null;
  email: string | null;
  phone: string | null;
  /** False when no users document answers to the parent id: no Billing tab. */
  has_account: boolean;
  stage: FamilyStage;
  children: FamilyIndexChild[];
  card_on_file: boolean | null;
  registration: RegistrationState | null;
  /** Null when money is hidden from this caller or could not be read. */
  money: FamilyIndexMoney | null;
  matched_parent: boolean;
}

export interface FamilyIndexPage {
  generated_at: string;
  families: FamilyIndexRow[];
  total: number;
  page: number;
  page_size: number;
  money_visible: boolean;
  warnings: string[];
}

export interface FamilyViewPreset {
  id: string;
  label: string;
  params: Record<string, string>;
  money: boolean;
}

export interface FamilyIndexSummary {
  generated_at: string;
  total_families: number;
  tiles: Partial<Record<FamilyScope, number>>;
  counts_by_stage: Partial<Record<FamilyStage, number>>;
  presets: FamilyViewPreset[];
  /** Families each non-scope preset keeps, by preset id (`no_card`; `overdue`
   * only when money is visible). Optional: older responses omit it. */
  preset_counts?: Partial<Record<string, number>>;
  warnings: string[];
}

export interface FamilyIndexParams {
  search?: string;
  scope?: FamilyScope;
  stage?: FamilyStage[];
  class_id?: string;
  card_on_file?: boolean;
  overdue?: boolean;
  sort?: FamilyIndexSort;
  order?: "asc" | "desc";
  page?: number;
  page_size?: number;
}

export function familyIndexQueryString(params: FamilyIndexParams): string {
  const search = new URLSearchParams();
  if (params.search) search.set("search", params.search);
  if (params.scope) search.set("scope", params.scope);
  for (const stage of params.stage ?? []) search.append("stage", stage);
  if (params.class_id) search.set("class_id", params.class_id);
  if (params.card_on_file !== undefined) search.set("card_on_file", String(params.card_on_file));
  if (params.overdue !== undefined) search.set("overdue", String(params.overdue));
  if (params.sort) search.set("sort", params.sort);
  if (params.order) search.set("order", params.order);
  if (params.page) search.set("page", String(params.page));
  if (params.page_size) search.set("page_size", String(params.page_size));
  return search.toString();
}

export function fetchFamilyIndex(params: FamilyIndexParams = {}): Promise<FamilyIndexPage> {
  const qs = familyIndexQueryString(params);
  return apiFetch<FamilyIndexPage>(`/admin/families${qs ? `?${qs}` : ""}`, { method: "GET" });
}

export function fetchFamilyIndexSummary(): Promise<FamilyIndexSummary> {
  return apiFetch<FamilyIndexSummary>("/admin/families/summary", { method: "GET" });
}

// ---------------------------------------------------------------------------
// People CRM family record page (Lane A4). Shapes mirror
// backend/v2/interfaces/admin/family_index_views.py (AdminFamilyRecordView)
// and backend/v2/interfaces/admin/family_record_routes.py.
// ---------------------------------------------------------------------------

/** `GET /admin/families/{familyId}/record`: the family's index row. */
export interface FamilyRecordView {
  generated_at: string;
  /** The canonical family id, whichever alias the request URL carried. */
  family_id: string;
  family: FamilyIndexRow;
  money_visible: boolean;
  warnings: string[];
}

export function fetchFamilyRecord(familyId: string): Promise<FamilyRecordView> {
  return apiFetch<FamilyRecordView>(
    `/admin/families/${encodeURIComponent(familyId)}/record`,
    { method: "GET" },
  );
}

/** A coach note the coach shared with the family (#665), read-only. */
export interface StudentCoachNote {
  note_id: string;
  session_id: string | null;
  session_title: string | null;
  coach_name: string | null;
  body: string;
  created_at: string;
}

export interface StudentCoachNoteList {
  student_id: string;
  notes: StudentCoachNote[];
}

export function fetchStudentCoachNotes(studentId: string): Promise<StudentCoachNoteList> {
  return apiFetch<StudentCoachNoteList>(
    `/admin/students/${encodeURIComponent(studentId)}/coach-notes`,
    { method: "GET" },
  );
}

export type CorrectableAttendanceStatus = "present" | "absent" | "late";

export interface CorrectedAttendance {
  attendance_id: string;
  occurrence_id: string;
  session_id: string;
  student_id: string;
  status: CorrectableAttendanceStatus;
  previous_status: CorrectableAttendanceStatus | "voided" | null;
  corrected_by: string | null;
  corrected_at: string | null;
}

/**
 * Admin correction of one recorded mark (#517): any time, no coach window.
 * The backend keeps the previous status, the admin and the reason on the row
 * and emits `Coaching.AttendanceCorrected`.
 */
export function correctStudentAttendance(
  occurrenceId: string,
  studentId: string,
  payload: { status: CorrectableAttendanceStatus; reason: string | null },
): Promise<CorrectedAttendance> {
  return apiFetch<CorrectedAttendance>(
    `/admin/session-occurrences/${encodeURIComponent(occurrenceId)}/attendance/${encodeURIComponent(studentId)}`,
    { method: "PATCH", body: JSON.stringify(payload) },
  );
}
