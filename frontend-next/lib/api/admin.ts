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

export type EnrollmentStatus = "active" | "paused" | "cancelled";

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

export type PaymentStatus = "succeeded" | "pending" | "refunded" | "partially_refunded" | "failed";

export interface AdminPaymentView {
  payment_id: string;
  parent_id: string;
  student_id: string | null;
  session_id: string | null;
  amount_cents: number;
  currency: string;
  status: PaymentStatus;
  refunded_cents: number;
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

export interface AdminPayoutView {
  payout_id: string;
  amount_cents: number;
  currency: string;
  arrival_date: string;
  status: string;
}

export interface AdminPayoutList {
  payouts: AdminPayoutView[];
}

export interface AdminExpenseView {
  expense_id: string;
  category: string;
  amount_cents: number;
  note: string | null;
  incurred_on: string; // YYYY-MM-DD
  created_at: string;
}

export interface AdminExpenseList {
  expenses: AdminExpenseView[];
}

export interface CreateExpenseRequest {
  category: string;
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

// ---------------------------------------------------------------------------
// Sessions
// ---------------------------------------------------------------------------

export function listAdminSessions(date?: string): Promise<AdminSessionList> {
  const q = date ? `?date=${encodeURIComponent(date)}` : "";
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

export function deleteEnrollment(enrollmentId: string): Promise<void> {
  return apiFetch<void>(`/admin/enrollments/${enrollmentId}`, { method: "DELETE" });
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
