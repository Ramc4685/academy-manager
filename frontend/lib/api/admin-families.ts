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

export interface FamilyHeader {
  balance_cents: number;
  open_invoice_count: number;
  available_credit_cents: number;
  last_payment: FamilyLastPayment | null;
  autopay: FamilyAutopay;
  registration: FamilyRegistration;
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
