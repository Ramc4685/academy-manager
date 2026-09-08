/**
 * Autopay opt-in at payment time — checkbox visibility + default-state rules
 * for the parent Payments page (spec:
 * docs/superpowers/specs/2026-07-05-autopay-optin-at-payment-design.md).
 *
 * The checkbox ("Enroll in autopay for future invoices") renders under a Pay
 * button only when there is something to enroll: at least one covered
 * enrollment whose autopay_enrollment_status is NOT already
 * active/setup_started/paused. When an invoice has no enrollment linkage at
 * all (legacy / non-enrollment invoice) we default to SHOWING the checkbox
 * (the backend simply has nothing to enroll, so over-showing is harmless).
 *
 * An invoice that DOES name an enrollment which is absent from the parent's
 * enrollment list — or present but no longer active/paused — is the final
 * invoice of a cancelled/withdrawn enrollment (issue #651). There is nothing
 * left to enroll, so the checkbox is hidden rather than pre-checked.
 */

export const AUTOPAY_OPTIN_LABEL = "Enroll in autopay for future invoices";

/** Statuses with nothing to offer: autopay is already on or in-flight. */
const ENROLLED_AUTOPAY_STATUSES = new Set(["active", "setup_started", "paused"]);

/** Enrollment lifecycle statuses that can still carry autopay. */
const ENROLLABLE_ENROLLMENT_STATUSES = new Set(["active", "paused"]);

export interface AutopayOptinEnrollment {
  enrollment_id: string;
  /** Enrollment lifecycle status (active/paused/cancelled/withdrawn); absent = active. */
  status?: string | null;
  autopay_enrollment_status?: string | null;
}

export interface AutopayOptinInvoice {
  status: string;
  balance_due_cents: number;
  enrollment_id?: string | null;
}

export function isEnrolledInAutopay(
  enrollment: Pick<AutopayOptinEnrollment, "autopay_enrollment_status">,
): boolean {
  return ENROLLED_AUTOPAY_STATUSES.has(enrollment.autopay_enrollment_status ?? "");
}

/**
 * Single-invoice Pay button: show the checkbox unless the invoice's
 * enrollment is already enrolled, or is gone/no longer active (nothing to
 * enroll). Only an invoice with no enrollment linkage at all defaults to
 * showing.
 */
export function showAutopayOptinForInvoice(
  invoice: Pick<AutopayOptinInvoice, "enrollment_id">,
  enrollments: AutopayOptinEnrollment[],
): boolean {
  if (!invoice.enrollment_id) return true;
  const enrollment = enrollments.find(
    (candidate) => candidate.enrollment_id === invoice.enrollment_id,
  );
  if (!enrollment) return false;
  if (!ENROLLABLE_ENROLLMENT_STATUSES.has(enrollment.status ?? "active")) return false;
  return !isEnrolledInAutopay(enrollment);
}

/**
 * Pay-balance button: show the checkbox when any covered open invoice's
 * enrollment is not already enrolled. "Covered" mirrors the balance-hero
 * total: non-void invoices with a balance due.
 */
export function showAutopayOptinForBalance(
  invoices: AutopayOptinInvoice[],
  enrollments: AutopayOptinEnrollment[],
): boolean {
  return invoices
    .filter((invoice) => invoice.balance_due_cents > 0 && invoice.status !== "void")
    .some((invoice) => showAutopayOptinForInvoice(invoice, enrollments));
}

/** Checkbox state: checked by default until the parent explicitly toggles it. */
export function resolveEnrollAutopayChecked(state: boolean | undefined): boolean {
  return state ?? true;
}
