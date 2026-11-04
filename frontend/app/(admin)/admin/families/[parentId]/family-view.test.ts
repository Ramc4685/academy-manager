import { describe, expect, it } from "vitest";

import {
  autopayToggle,
  currentPeriod,
  defaultDueDate,
  enrollmentOptions,
  enrollmentPriceCents,
  familyRefundLine,
  invoiceActionLabel,
  invoiceDueDays,
  invoiceRefundLabel,
  periodLabel,
  refundableCents,
  refundLabel,
  registrationChips,
  shortDate,
  timelineEmphasis,
  timelineKindLabel,
  timelineTone,
  tuitionLineDescription,
  undeliverableChip,
} from "./family-view";
import type {
  FamilyEnrollment,
  FamilyHeader,
  FamilyInvoice,
  FamilyStudent,
} from "@/lib/api/admin-families";
import {
  CARD_LABELS,
  LOGIN_LABELS,
  cardChip,
  cardStateFromRegistration,
} from "@/lib/people-status";

describe("autopayToggle", () => {
  const base = {
    active_count: 1,
    total_count: 2,
    card_last4: "4242",
    card_label: "Visa",
    next_charge_on: "2026-09-08",
    next_charge_invoice_id: "inv-1",
    last_failure: null,
  };
  it("on: checked, enabled, shows card and next charge", () => {
    expect(autopayToggle({ ...base, state: "on" })).toEqual({
      checked: true,
      disabled: false,
      label: "On",
      hint: "Visa ••4242 · next charge Sep 8",
    });
  });
  it("partial: checked with a count", () => {
    expect(autopayToggle({ ...base, state: "partial" }).label).toBe("On for 1 of 2");
  });
  it("off: unchecked, enabled", () => {
    expect(autopayToggle({ ...base, state: "off", next_charge_on: null })).toMatchObject({
      checked: false,
      disabled: false,
      label: "Off",
    });
  });
  it("needs_consent: disabled with the invite hint", () => {
    expect(
      autopayToggle({
        ...base,
        state: "needs_consent",
        card_last4: null,
        card_label: null,
        next_charge_on: null,
      }),
    ).toEqual({
      checked: false,
      disabled: true,
      label: "Off",
      hint: "Needs parent consent — send invite",
    });
  });
});

describe("dates", () => {
  it("shortDate renders an academy-local ISO date without a timezone shift", () => {
    expect(shortDate("2026-09-08")).toBe("Sep 8");
    expect(shortDate("2026-12-31T05:00:00Z")).toBe("Dec 31");
    expect(shortDate(null)).toBeNull();
    expect(shortDate("garbage")).toBeNull();
  });
  it("periodLabel renders YYYY-MM", () => {
    expect(periodLabel("2026-09")).toBe("Sep 2026");
    expect(periodLabel("weird")).toBe("weird");
  });
});

describe("labels and chips", () => {
  it("maps invoice actions", () => {
    expect(invoiceActionLabel("charge_card")).toBe("Charge card now");
    expect(invoiceActionLabel("discount_once")).toBe("One-time discount");
  });
  it("splits registration into the two shared People facts (#840)", () => {
    expect(registrationChips("registered")).toEqual({
      login: { label: "Active", variant: "enrolled" },
      card: { label: "Card on file", variant: "paid" },
    });
    expect(registrationChips("invited")).toEqual({
      login: { label: "Invited", variant: "pending" },
      card: { label: "No card", variant: "manual" },
    });
    expect(registrationChips("not_invited")).toEqual({
      login: { label: "Not invited", variant: "manual" },
      card: { label: "No card", variant: "manual" },
    });
  });
  it("takes its wording from the one map the families list uses", () => {
    // The guarantee the issue asks for: the list page and this page cannot
    // drift because neither owns the strings.
    expect(registrationChips("registered").card.label).toBe(CARD_LABELS.on_file);
    expect(registrationChips("invited").card.label).toBe(CARD_LABELS.no_card);
    expect(registrationChips("not_invited").login.label).toBe(LOGIN_LABELS.not_invited);
    expect(registrationChips("registered").card).toEqual(
      cardChip(cardStateFromRegistration("card_on_file")),
    );
  });
  it("mutes comms rows", () => {
    expect(timelineTone({ kind: "comms", muted: true })).toBe("muted");
    expect(timelineTone({ kind: "money", muted: false })).toBe("money");
    expect(timelineTone({ kind: "coach", muted: false })).toBe("coach");
  });
  it("labels every unified timeline kind and emphasises money and admin rows", () => {
    expect(timelineKindLabel("coach")).toBe("Coach");
    expect(timelineKindLabel("crm")).toBe("Team");
    expect(timelineKindLabel("requests")).toBe("Request");
    expect(timelineKindLabel("something-new")).toBe("Activity");
    expect(timelineEmphasis("money")).toBe(true);
    expect(timelineEmphasis("admin")).toBe(true);
    expect(timelineEmphasis("attendance")).toBe(false);
  });
});

describe("manual invoice defaults", () => {
  it("currentPeriod uses the viewer's own calendar month", () => {
    expect(currentPeriod(new Date(2026, 8, 12))).toBe("2026-09");
    expect(currentPeriod(new Date(2026, 0, 1))).toBe("2026-01");
  });
  it("defaultDueDate lands a week out and rolls the month", () => {
    expect(defaultDueDate(new Date(2026, 8, 12))).toBe("2026-09-19");
    expect(defaultDueDate(new Date(2026, 8, 28))).toBe("2026-10-05");
  });
  it("defaultDueDate honours the academy's window", () => {
    expect(defaultDueDate(new Date(2026, 8, 12), 10)).toBe("2026-09-22");
    expect(defaultDueDate(new Date(2026, 8, 12), 0)).toBe("2026-09-12");
  });
  it("invoiceDueDays reads Billing rules, falling back only when unset (#739)", () => {
    expect(invoiceDueDays({ billing_day: 1, invoice_due_days: 10 })).toBe(10);
    // A configured 0 means "due today"; it must not read as "unset".
    expect(invoiceDueDays({ billing_day: 1, invoice_due_days: 0 })).toBe(0);
    expect(invoiceDueDays(undefined)).toBe(7);
    expect(invoiceDueDays(null)).toBe(7);
  });
  it("tuitionLineDescription matches the monthly generator's wording", () => {
    expect(tuitionLineDescription("2026-09")).toBe("Monthly tuition 2026-09");
  });
});

describe("enrollment pricing", () => {
  const enrollment: FamilyEnrollment = {
    enrollment_id: "enr-1",
    session_id: "ses-1",
    session_title: "Tue/Thu Intermediate",
    schedule: null,
    status: "active",
    monthly_price_cents: 12000,
    override_price_cents: null,
    autopay_status: null,
    recurring_discount: null,
    resume_on: null,
    actions: [],
  };
  it("prefers the override price", () => {
    expect(enrollmentPriceCents(enrollment)).toBe(12000);
    expect(enrollmentPriceCents({ ...enrollment, override_price_cents: 9000 })).toBe(9000);
    expect(enrollmentPriceCents({ ...enrollment, monthly_price_cents: null })).toBeNull();
  });
  it("flattens students into one labelled list", () => {
    const students: FamilyStudent[] = [
      { student_id: "stu-1", name: "Arjun", status: "active", enrollments: [enrollment] },
      { student_id: "stu-2", name: "Meera", status: "active", enrollments: [] },
    ];
    expect(enrollmentOptions(students)).toEqual([
      {
        enrollment_id: "enr-1",
        student_id: "stu-1",
        student_name: "Arjun",
        label: "Arjun · Tue/Thu Intermediate",
        price_cents: 12000,
      },
    ]);
  });
  it("carries no Bill-this-month quote, because only the backend can price the month", () => {
    // The month's charge depends on proration and the four-class rule (#724); a flat
    // client-side figure was wrong for exactly the first month that matters.
    const [option] = enrollmentOptions([
      { student_id: "stu-1", name: "Arjun", status: "active", enrollments: [enrollment] },
    ]);
    expect(option).not.toHaveProperty("bill_period_price_cents");
  });
  it("falls back to Class when the session has no title", () => {
    const students: FamilyStudent[] = [
      {
        student_id: "stu-1",
        name: "Arjun",
        status: "active",
        enrollments: [{ ...enrollment, session_title: null }],
      },
    ];
    expect(enrollmentOptions(students)[0].label).toBe("Arjun · Class");
  });
});


describe("undeliverableChip", () => {
  it("is silent when the address is deliverable, missing or not reported", () => {
    expect(undeliverableChip(undefined)).toBeNull();
    expect(
      undeliverableChip({ undeliverable: false, since: null, reason: null, email: "a@b.com" }),
    ).toBeNull();
    // Flagged but with no date: nothing honest to show, so show nothing.
    expect(
      undeliverableChip({ undeliverable: true, since: null, reason: "hard_bounce", email: null }),
    ).toBeNull();
  });

  it("names the date the address went dead, so the chip is actionable", () => {
    const chip = undeliverableChip({
      undeliverable: true,
      since: "2026-09-02T08:30:00+00:00",
      reason: "hard_bounce",
      email: "s@example.com",
    });
    expect(chip).toEqual({
      label: "Email undeliverable since Sep 2",
      variant: "failed",
      detail: "Nothing we send reaches s@example.com. Ask for a new address.",
    });
  });

  it("says what a spam complaint actually blocks, rather than overstating it", () => {
    const chip = undeliverableChip({
      undeliverable: true,
      since: "2026-09-04T09:00:00+00:00",
      reason: "complaint",
      email: "s@example.com",
    });
    expect(chip?.label).toBe("Marked as spam on Sep 4");
    expect(chip?.variant).toBe("pending");
    expect(chip?.detail).toContain("Invoices still send");
  });
});

describe("refunds (#929)", () => {
  function invoice(overrides: Partial<FamilyInvoice> = {}): FamilyInvoice {
    return {
      invoice_id: "inv-1",
      invoice_number: null,
      period: "2026-09",
      student_id: null,
      student_name: null,
      enrollment_id: null,
      status: "paid",
      total_cents: 6000,
      paid_cents: 6000,
      balance_due_cents: 0,
      due_date: null,
      created_at: null,
      paid_at: null,
      voided_at: null,
      void_reason: null,
      settlement_unlinked: false,
      delivery: { status: "sent", last_sent_at: null, kind: "invoice" },
      allocations: [
        {
          payment_id: "pay-1",
          amount_cents: 4000,
          method: "card",
          paid_at: null,
          stripe_payment_intent_id: "pi_1",
        },
        {
          payment_id: "pay-2",
          amount_cents: 2000,
          method: "cash",
          paid_at: null,
          stripe_payment_intent_id: null,
        },
      ],
      credits: [],
      chargeable: false,
      actions: [],
      ...overrides,
    };
  }

  it("says nothing when nothing came back", () => {
    expect(refundLabel(6000, 0)).toBeNull();
    expect(refundLabel(6000, undefined)).toBeNull();
    expect(invoiceRefundLabel(invoice())).toBeNull();
  });

  it("shows refunded and net, preferring the backend's net", () => {
    expect(invoiceRefundLabel(invoice({ refunded_cents: 2500, net_paid_cents: 3500 }))).toBe(
      "$25.00 refunded · $35.00 net",
    );
    // Older payload without a net: paid minus refunded, never negative.
    expect(refundLabel(1000, 2500)).toBe("$25.00 refunded · $0.00 net");
  });

  it("family totals line only when the family had a refund", () => {
    const header = { paid_cents: 7000, refunded_cents: 5000, net_paid_cents: 2000 } as FamilyHeader;
    expect(familyRefundLine(header)).toBe("Paid $70.00 · $50.00 refunded · $20.00 net");
    expect(familyRefundLine({ ...header, refunded_cents: 0 })).toBeNull();
    expect(familyRefundLine({} as FamilyHeader)).toBeNull();
  });

  it("refund ceiling is card money minus what was already refunded", () => {
    expect(refundableCents(invoice())).toBe(4000);
    expect(refundableCents(invoice({ refunded_cents: 1500 }))).toBe(2500);
    expect(refundableCents(invoice({ refunded_cents: 9000 }))).toBe(0);
  });
});
