/**
 * Stub payload for `GET /admin/billing/rules`, shaped exactly like the
 * backend assembler's view (spec 2026-09-07-billing-rules-design §3).
 * Shared by the Billing rules spec and the admin-shell tab matrix.
 */
export function billingRulesFixture(
  overrides: Partial<Record<string, number>> = {},
): Record<string, unknown> {
  const value = (key: string, fallback: number) => overrides[key] ?? fallback;
  const editable = (
    key: string,
    label: string,
    fallback: number,
    unit: string,
    min: number,
    max: number,
  ) => ({
    key,
    label,
    editable: true,
    value: value(key, fallback),
    unit,
    min_value: min,
    max_value: max,
    display: null,
    detail: null,
  });
  const fixed = (key: string, label: string, display: string, detail: string | null = null) => ({
    key,
    label,
    editable: false,
    value: null,
    unit: null,
    min_value: null,
    max_value: null,
    display,
    detail,
  });

  return {
    groups: [
      {
        key: "monthly_invoicing",
        title: "Monthly invoicing",
        note: null,
        rows: [
          editable("billing_day", "Invoice day of month", 1, "day_of_month", 1, 28),
          editable("invoice_due_days", "Days until due", 7, "days", 0, 60),
          fixed(
            "autopay_charge_time",
            "Autopay charge time",
            "09:00 academy time on the due date",
            "The dunning worker prepares the first attempt from this hour in the academy's timezone.",
          ),
          fixed(
            "retry_schedule",
            "Retry schedule after a failed charge",
            "same day, then 3, 5 and 7 days later, then autopay switches off",
            "4 attempts in total, then the enrollment's autopay is switched off.",
          ),
        ],
      },
      {
        key: "late_payments",
        title: "Late payments",
        note: "Not applied automatically yet — these values are stored for when late fees ship.",
        rows: [
          editable("grace_days", "Grace days after due", 5, "days", 0, 60),
          editable("late_fee_cents", "Late fee", 1500, "cents", 0, 100000),
        ],
      },
      {
        key: "leaving_and_pausing",
        title: "Leaving and pausing",
        note: null,
        rows: [
          fixed(
            "cancel_mid_month",
            "Cancel mid-month",
            "Full month owed, no refund",
            "Self-cancellation keeps the cancellation month payable and voids later invoices.",
          ),
          fixed(
            "join_mid_month",
            "Join mid-month",
            "Prorated from the start date",
            "Proration policy first-month-proration-v1.",
          ),
          fixed(
            "paused_months",
            "Paused months",
            "Not invoiced",
            "The monthly generator skips paused enrollments.",
          ),
          editable(
            "cancellation_minimum_notice_days",
            "Cancellation notice",
            14,
            "days",
            0,
            90,
          ),
          editable("cancellation_fee_cents", "Late-cancellation fee", 0, "cents", 0, 100000),
        ],
      },
      {
        key: "parent_messages",
        title: "Parent messages",
        note: null,
        rows: [
          fixed(
            "autopay_notice",
            "Autopay notice on invoice day",
            "On",
            "Autopay parents get a notice instead of the invoice email.",
          ),
          fixed("charge_receipt", "Receipt after a successful charge", "On"),
          fixed("failure_notice", "Payment failure notice", "Sent by the dunning ladder"),
          fixed(
            "manual_payer_reminders",
            "Reminders to manual payers",
            "Sent by hand from Payments. No automatic schedule.",
          ),
        ],
      },
    ],
  };
}
