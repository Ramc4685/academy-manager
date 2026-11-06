/**
 * Compile-time contract between the hand-written billing client types and the
 * backend's real responses (generated from openapi.snapshot.json).
 *
 * Each line asserts "what the server returns fits what the screen expects".
 * If the backend renames, drops, or retypes a field a screen reads, typecheck
 * fails here instead of the page breaking in production. Types only; emits no JS.
 *
 * Not checkable yet, because the backend declares no response model for them:
 * POST /admin/students/{id}/invoices and POST /admin/enrollments/{id}/invoices/bill-period.
 * Add them here once they get one.
 */
import type { paths } from "./generated/v2";
import type {
  AdminCollectionsView,
  AdminFamilyLastPaymentsResponse,
  AdminPaymentFeedResponse,
  AdminPaymentList,
  AdminPaymentView,
  BillingSetupAutopayEnableResponse,
  InvoiceAuditResponse,
  RefundResponse,
  FailedPaymentsResponse,
  GenerateMonthlyPaymentsResponse,
  InvoiceAttemptsResponse,
  InvoiceScheduleView,
} from "./admin";
import type { AdminFamilyBillingView, PauseFamilyAutopayResponse } from "./admin-families";
import type {
  ParentCreditBalance,
  ParentInvoice,
  ParentInvoiceDetail,
  ParentPayment,
} from "./parent";

type Json<R> = R extends { content: { "application/json": infer B } } ? B : never;
type Ok<R> = R extends { 200: infer A } ? Json<A> : R extends { 201: infer A } ? Json<A> : never;
/**
 * FastAPI serializes every field, sending null for an unset default, so a field
 * the schema marks optional is always present. Not true for routes declared with
 * response_model_exclude_none=True; do not list those here.
 */
type Present<T> = T extends (infer U)[]
  ? Present<U>[]
  : T extends object
    ? { [K in keyof T]-?: Present<Exclude<T[K], undefined>> }
    : T;
type Res<P extends keyof paths, M extends keyof paths[P]> = paths[P][M] extends {
  responses: infer R;
}
  ? Present<Ok<R>>
  : never;
/** True only when the server's response is assignable to the client's type. */
type Fits<Server, Client> = [Server] extends [never]
  ? false
  : [Server] extends [Client]
    ? true
    : false;
type Expect<T extends true> = T;

// One alias per endpoint, so a failure names the endpoint that drifted.

// Parent money screens
export type ParentPaymentsFit = Expect<
  Fits<Res<"/api/v2/parent/payments", "get">, { payments: ParentPayment[] }>
>;
export type ParentInvoicesFit = Expect<
  Fits<Res<"/api/v2/parent/invoices", "get">, { invoices: ParentInvoice[] }>
>;
export type ParentInvoiceDetailFit = Expect<
  Fits<Res<"/api/v2/parent/invoices/{invoice_id}", "get">, ParentInvoiceDetail>
>;
export type ParentCreditsFit = Expect<Fits<Res<"/api/v2/parent/credits", "get">, ParentCreditBalance>>;
export type ParentPayInvoiceFit = Expect<
  Fits<
    Res<"/api/v2/parent/invoices/{invoice_id}/pay", "post">,
    { invoice_id: string; redirect_url: string }
  >
>;
export type ParentPayBalanceFit = Expect<
  Fits<Res<"/api/v2/parent/invoices/pay-balance", "post">, { redirect_url: string }>
>;
export type ParentCheckoutFit = Expect<
  Fits<Res<"/api/v2/parent/checkout/start", "post">, { payment_id: string; redirect_url: string }>
>;

// Admin money screens
// The backend types status as a plain string; the screen narrows it to known
// values and falls back for anything else, so only the other fields are pinned.
export type AdminPaymentsFit = Expect<
  Fits<
    Res<"/api/v2/admin/payments", "get">,
    Omit<AdminPaymentList, "payments"> & {
      payments: (Omit<AdminPaymentView, "status"> & { status: string })[];
    }
  >
>;
export type AdminPaymentFeedFit = Expect<
  Fits<Res<"/api/v2/admin/payments/feed", "get">, AdminPaymentFeedResponse>
>;
export type AdminCollectionsFit = Expect<
  Fits<Res<"/api/v2/admin/payments/collections", "get">, AdminCollectionsView>
>;
export type AdminLastPaymentsFit = Expect<
  Fits<Res<"/api/v2/admin/payments/last-by-family", "get">, AdminFamilyLastPaymentsResponse>
>;
export type AdminGenerateMonthlyFit = Expect<
  Fits<Res<"/api/v2/admin/payments/generate-monthly", "post">, GenerateMonthlyPaymentsResponse>
>;
export type AdminInvoiceScheduleFit = Expect<
  Fits<Res<"/api/v2/admin/billing/settings/invoice-schedule", "get">, InvoiceScheduleView>
>;
export type AdminFailedPaymentsFit = Expect<
  Fits<Res<"/api/v2/admin/billing/failed-payment-attempts", "get">, FailedPaymentsResponse>
>;
export type AdminInvoiceAttemptsFit = Expect<
  Fits<Res<"/api/v2/admin/billing/invoices/{invoice_id}/attempts", "get">, InvoiceAttemptsResponse>
>;
export type AdminEnableAutopayFit = Expect<
  Fits<
    Res<"/api/v2/admin/billing/setup/{parent_id}/autopay/enable", "post">,
    BillingSetupAutopayEnableResponse
  >
>;
export type AdminFamilyBillingFit = Expect<
  Fits<Res<"/api/v2/admin/families/{parent_id}/billing", "get">, AdminFamilyBillingView>
>;
export type AdminPauseAutopayFit = Expect<
  Fits<Res<"/api/v2/admin/families/{parent_id}/autopay/pause", "post">, PauseFamilyAutopayResponse>
>;
export type AdminRefundFit = Expect<Fits<Res<"/api/v2/admin/payments/refund", "post">, RefundResponse>>;
export type AdminInvoiceAuditFit = Expect<
  Fits<Res<"/api/v2/admin/billing/invoices/{invoice_id}/audit", "get">, InvoiceAuditResponse>
>;
