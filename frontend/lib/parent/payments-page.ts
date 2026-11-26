/** Parent Payments page decisions kept pure so they can be unit-tested (S24). */

type AutopayEnrollment = {
  departed?: boolean | null;
  payment_mode?: string | null;
  autopay_enrollment_status?: string | null;
  autopay_offer?: string | null;
};

// A set-up autopay must stay visible even when a new start would be refused.
const AUTOPAY_EXISTS = new Set(["active", "paused", "setup_started"]);

/** True when at least one class has an autopay the parent can start or see. */
export function autopayConfigurable(enrollments: AutopayEnrollment[]): boolean {
  return enrollments.some(
    (e) =>
      !e.departed &&
      ((e.autopay_offer ?? "available") === "available" ||
        AUTOPAY_EXISTS.has(e.autopay_enrollment_status ?? "")),
  );
}

/** What an empty Invoices list tells a family about when and how they pay. */
export function emptyInvoicesCopy(manualPaymentsOnly: boolean): { title: string; body: string } {
  return {
    title: "No invoices yet",
    body: manualPaymentsOnly
      ? "Your first invoice shows up here once a class is confirmed. Monthly classes get one invoice a month, and we email you each one. Your academy takes payment in person, so there is nothing to pay online."
      : "Your first invoice shows up here once a class is confirmed. Monthly classes get one invoice a month, and we email you each one. You can pay it here by card or bank account, or turn on autopay so it is paid for you.",
  };
}
