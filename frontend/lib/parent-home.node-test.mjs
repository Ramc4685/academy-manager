import assert from "node:assert/strict";
import { test } from "node:test";

import {
  attendanceCopy,
  balanceBannerCopy,
  buildParentHomeModel,
  findPaymentNeedingAttention,
  formatMoney,
  milestoneCopy,
  nextSessionCopy,
  progressPercent,
  shouldShowBalanceBanner,
} from "./parent-home.ts";

function failedPayment(overrides = {}) {
  return {
    payment_id: "p-failed",
    amount_cents: 9000,
    currency: "usd",
    status: "failed",
    refunded_cents: 0,
    created_at: "2026-06-06T12:00:00Z",
    session_id: "session-1",
    invoice_id: "inv-1",
    ...overrides,
  };
}

function invoiceRow(status, overrides = {}) {
  return {
    invoice_id: "inv-1",
    period: "2026-06",
    status,
    total_cents: 9000,
    balance_due_cents: status === "paid" ? 0 : 9000,
    currency: "usd",
    due_date: "2026-06-15",
    pdf_url: null,
    created_at: "2026-06-01T00:00:00Z",
    ...overrides,
  };
}

function homeInputWithFailedPayment({ enrollments, invoices, payments = [failedPayment()] }) {
  return {
    children: [
      {
        student_id: "s1",
        full_name: "Rohan Rao",
        status: "active",
        active_session_count: 1,
        attended_count: 0,
        absent_count: 0,
      },
    ],
    enrollments,
    attendance: [],
    notes: [],
    payments,
    invoices,
    credits: { balance_cents: 0, credits: [] },
    waiver: null,
    progressRows: [],
  };
}

const activeEnrollment = {
  enrollment_id: "e1",
  student_id: "s1",
  student_name: "Rohan Rao",
  session_id: "session-1",
  session_title: "Intermediate Badminton",
  status: "active",
  payment_mode: "monthly",
  subscription_status: null,
};

test("failed payment on an open invoice still needs attention", () => {
  const model = buildParentHomeModel(
    homeInputWithFailedPayment({
      enrollments: [activeEnrollment],
      invoices: [invoiceRow("open")],
    }),
  );
  assert.equal(model.primaryAction.kind, "payment");
  // Without invoice data the payment-only behaviour is unchanged.
  const legacy = buildParentHomeModel(
    homeInputWithFailedPayment({ enrollments: [activeEnrollment], invoices: undefined }),
  );
  assert.equal(legacy.primaryAction.kind, "payment");
});

test("failed payment whose invoice was voided or paid no longer needs attention (#651)", () => {
  for (const status of ["void", "paid"]) {
    const model = buildParentHomeModel(
      homeInputWithFailedPayment({
        enrollments: [activeEnrollment],
        invoices: [invoiceRow(status, { void_reason: status === "void" ? "enrollment_cancelled" : null })],
      }),
    );
    assert.notEqual(model.primaryAction.kind, "payment", status);
    assert.equal(model.primaryAction.kind, "next_class", status);
  }
});

test("failed payment is not surfaced when the parent has no active enrollment", () => {
  const cancelled = { ...activeEnrollment, status: "cancelled" };
  const model = buildParentHomeModel(
    homeInputWithFailedPayment({
      enrollments: [cancelled],
      invoices: [invoiceRow("open")],
    }),
  );
  assert.equal(model.primaryAction.kind, "register");
  assert.equal(
    findPaymentNeedingAttention({
      payments: [failedPayment()],
      invoices: [],
      hasActiveEnrollment: false,
    }),
    null,
  );
});

test("findPaymentNeedingAttention matches by invoice_id and ignores unlinked payments' invoices", () => {
  const voided = invoiceRow("void");
  // Same failed payment, but linked to a different (still open) invoice.
  const stillOpen = findPaymentNeedingAttention({
    payments: [failedPayment({ invoice_id: "inv-other" })],
    invoices: [voided, invoiceRow("open", { invoice_id: "inv-other" })],
    hasActiveEnrollment: true,
  });
  assert.equal(stillOpen?.payment_id, "p-failed");
  // A failed payment with no invoice linkage cannot be cleared by the ledger.
  const unlinked = findPaymentNeedingAttention({
    payments: [failedPayment({ invoice_id: null })],
    invoices: [voided],
    hasActiveEnrollment: true,
  });
  assert.equal(unlinked?.payment_id, "p-failed");
  // Non-issue statuses are never surfaced.
  assert.equal(
    findPaymentNeedingAttention({
      payments: [failedPayment({ status: "succeeded" })],
      invoices: [],
      hasActiveEnrollment: true,
    }),
    null,
  );
});

test("builds selected child progress hero and latest note", () => {
  const model = buildParentHomeModel({
    children: [
      {
        student_id: "s1",
        full_name: "Rohan Rao",
        status: "active",
        active_session_count: 1,
        attended_count: 9,
        absent_count: 1,
      },
    ],
    enrollments: [
      {
        enrollment_id: "e1",
        student_id: "s1",
        student_name: "Rohan Rao",
        session_id: "session-1",
        session_title: "Intermediate Badminton",
        status: "active",
        payment_mode: "monthly",
        subscription_status: "active",
      },
    ],
    attendance: [
      {
        attendance_id: "a1",
        student_id: "s1",
        student_name: "Rohan Rao",
        session_id: "session-1",
        session_title: "Intermediate Badminton",
        status: "present",
        marked_at: "2026-06-07T18:00:00Z",
        coach_name: "Coach Mani",
      },
    ],
    notes: [
      {
        note_id: "n1",
        student_id: "s1",
        student_name: "Rohan Rao",
        session_id: "session-1",
        session_title: "Intermediate Badminton",
        coach_id: "c1",
        coach_name: "Coach Mani",
        body: "Footwork is getting sharper.",
        created_at: "2026-06-07T19:00:00Z",
      },
    ],
    payments: [
      {
        payment_id: "p1",
        amount_cents: 18000,
        currency: "usd",
        status: "succeeded",
        refunded_cents: 0,
        created_at: "2026-06-06T12:00:00Z",
        session_id: "session-1",
      },
    ],
    credits: { balance_cents: 0, credits: [] },
    waiver: {
      required: true,
      waiver_template_id: "w1",
      title: "Waiver",
      version: "v1",
      body: "Text",
      students: [
        {
          student_id: "s1",
          student_name: "Rohan Rao",
          status: "signed",
          signed_at: "2026-06-01T00:00:00Z",
          waiver_version: "v1",
        },
      ],
    },
    progressRows: [
      {
        student_id: "s1",
        student_name: "Rohan Rao",
        program_id: "prog",
        program_name: "Badminton",
        current_level_id: "l3",
        current_level_name: "L3 Serve and Lift",
        current_level_sequence: 3,
        required_skill_count: 10,
        required_skills_passed: 7,
        total_skill_count: 12,
        total_skills_passed: 8,
        in_progress_count: 3,
        not_started_count: 1,
        test_ready_count: 1,
        level_completion_status: "in_progress",
        level_up_status: null,
        certificate_count: 0,
        next_action: "continue_practice",
      },
    ],
  });

  assert.equal(model.selectedChild?.student_id, "s1");
  assert.equal(model.hero.percent, 67);
  assert.equal(model.latestNote?.body, "Footwork is getting sharper.");
  assert.equal(model.primaryAction.kind, "progress");
  assert.equal(model.recentActivity.length, 3);
});

test("prioritizes missing waiver as strongest action", () => {
  const model = buildParentHomeModel({
    children: [
      {
        student_id: "s1",
        full_name: "Rohan Rao",
        status: "active",
        active_session_count: 1,
        attended_count: 0,
        absent_count: 0,
      },
    ],
    enrollments: [],
    attendance: [],
    notes: [],
    payments: [],
    credits: { balance_cents: 0, credits: [] },
    waiver: {
      required: true,
      waiver_template_id: "w1",
      title: "Waiver",
      version: "v1",
      body: "Text",
      students: [
        {
          student_id: "s1",
          student_name: "Rohan Rao",
          status: "pending",
          signed_at: null,
          waiver_version: null,
        },
      ],
    },
    progressRows: [],
  });

  assert.equal(model.primaryAction.kind, "waiver");
});

test("an unsigned waiver on a NON-first child still surfaces (Home has no switcher)", () => {
  const child = (student_id, full_name) => ({
    student_id,
    full_name,
    status: "active",
    active_session_count: 1,
    attended_count: 0,
    absent_count: 0,
  });
  const model = buildParentHomeModel({
    children: [child("s1", "Ava Kim"), child("s2", "Bo Chen")],
    enrollments: [],
    attendance: [],
    notes: [],
    payments: [],
    credits: { balance_cents: 0, credits: [] },
    waiver: {
      required: true,
      waiver_template_id: "w1",
      title: "Waiver",
      version: "v1",
      body: "Text",
      students: [
        {
          student_id: "s1",
          student_name: "Ava Kim",
          status: "signed",
          signed_at: "2026-09-01T00:00:00Z",
          waiver_version: "v1",
        },
        {
          student_id: "s2",
          student_name: "Bo Chen",
          status: "pending",
          signed_at: null,
          waiver_version: null,
        },
      ],
    },
    progressRows: [],
  });

  assert.equal(model.primaryAction.kind, "waiver");
  assert.match(model.primaryAction.body, /Bo/);
});

test("recent activity spans the family, not just the first child", () => {
  const child = (student_id, full_name) => ({
    student_id,
    full_name,
    status: "active",
    active_session_count: 1,
    attended_count: 0,
    absent_count: 0,
  });
  const model = buildParentHomeModel({
    children: [child("s1", "Ava Kim"), child("s2", "Bo Chen")],
    enrollments: [],
    attendance: [
      {
        attendance_id: "a-bo",
        student_id: "s2",
        session_id: "session-1",
        session_title: "Junior Beginners",
        status: "absent",
        marked_at: "2026-09-04T12:00:00Z",
      },
    ],
    notes: [
      {
        note_id: "n-bo",
        student_id: "s2",
        student_name: "Bo Chen",
        coach_name: "Coach Lee",
        created_at: "2026-09-05T12:00:00Z",
        body: "Bo's clear is improving.",
      },
    ],
    payments: [],
    credits: { balance_cents: 0, credits: [] },
    waiver: null,
    progressRows: [],
  });

  assert.deepEqual(
    model.recentActivity.map((item) => item.id).sort(),
    ["attendance-a-bo", "note-n-bo"],
  );
});

test("handles no children with registration action", () => {
  const model = buildParentHomeModel({
    children: [],
    enrollments: [],
    attendance: [],
    notes: [],
    payments: [],
    credits: { balance_cents: 0, credits: [] },
    waiver: null,
    progressRows: [],
  });

  assert.equal(model.selectedChild, null);
  assert.equal(model.primaryAction.kind, "register");
});

test("does not treat paused enrollment as next class", () => {
  const model = buildParentHomeModel({
    children: [
      {
        student_id: "s1",
        full_name: "Rohan Rao",
        status: "active",
        active_session_count: 0,
        attended_count: 0,
        absent_count: 0,
      },
    ],
    enrollments: [
      {
        enrollment_id: "e1",
        student_id: "s1",
        student_name: "Rohan Rao",
        session_id: "session-1",
        session_title: "Paused Badminton",
        status: "paused",
        payment_mode: "monthly",
        subscription_status: "paused",
      },
    ],
    attendance: [],
    notes: [],
    payments: [],
    credits: { balance_cents: 0, credits: [] },
    waiver: null,
    progressRows: [],
  });

  assert.equal(model.nextEnrollment, null);
  assert.equal(model.primaryAction.kind, "register");
  assert.equal(model.hero.subtitle, "First skills will appear after coach assessment.");
});

/* --- kid-first home (slice 4) ------------------------------------------ */

function balance(overrides = {}) {
  return {
    amount_due_cents: 0,
    currency: "usd",
    due_date: null,
    open_invoice_count: 0,
    payment_failed: false,
    ...overrides,
  };
}

test("the balance banner shows only when money is due or a payment failed", () => {
  assert.equal(shouldShowBalanceBanner(balance()), false);
  assert.equal(shouldShowBalanceBanner(balance({ amount_due_cents: 12000 })), true);
  assert.equal(shouldShowBalanceBanner(balance({ payment_failed: true })), true);
  assert.equal(
    shouldShowBalanceBanner(balance({ amount_due_cents: 12000, payment_failed: true })),
    true,
  );
  // A zeroed balance with open invoices (fully credited) is still silent.
  assert.equal(shouldShowBalanceBanner(balance({ open_invoice_count: 2 })), false);
  assert.equal(shouldShowBalanceBanner(null), false);
});

test("banner copy leads with the amount and its due date", () => {
  assert.deepEqual(
    balanceBannerCopy(
      balance({ amount_due_cents: 12000, due_date: "2026-09-12", open_invoice_count: 1 }),
    ),
    { headline: "$120.00 due", detail: "Due Sep 12" },
  );
  // No due date, several invoices: say how many rather than inventing a date.
  assert.deepEqual(
    balanceBannerCopy(balance({ amount_due_cents: 5000, open_invoice_count: 3 })),
    { headline: "$50.00 due", detail: "3 open invoices" },
  );
  // One invoice with no due date (due_date is optional on ParentInvoice):
  // neither a date nor a count is available, so the detail invites the tap.
  assert.deepEqual(
    balanceBannerCopy(balance({ amount_due_cents: 5000, open_invoice_count: 1 })),
    { headline: "$50.00 due", detail: "Tap to pay your balance." },
  );
});

test("a failed payment outranks an amount due in the banner copy", () => {
  const copy = balanceBannerCopy(
    balance({ amount_due_cents: 12000, due_date: "2026-09-12", payment_failed: true }),
  );
  assert.equal(copy.headline, "Payment didn't go through");
  assert.equal(copy.detail, "Update your payment method to stay enrolled.");
});

test("attendance copy counts marked sessions and never fakes a zero", () => {
  assert.equal(attendanceCopy({ present: 6, total: 7 }), "6 of 7 sessions this month");
  assert.equal(attendanceCopy({ present: 0, total: 0 }), "No sessions marked yet this month");
  assert.equal(attendanceCopy(null), "No sessions marked yet this month");
});

test("next session renders in the academy timezone with a venue fallback", () => {
  const copy = nextSessionCopy(
    {
      occurrence_id: "occ-1",
      session_id: "sess-1",
      session_title: "Junior Beginners",
      location: "Court 2",
      start_at: "2026-09-10T23:00:00Z",
      end_at: "2026-09-11T00:00:00Z",
      coach_name: null,
    },
    "America/Chicago",
  );
  // 23:00 UTC is still Sep 10 (6:00 PM) in Chicago — not Sep 11.
  assert.equal(copy.when, "Thu, Sep 10 · 6:00 PM CDT");
  assert.equal(copy.where, "Court 2");

  const noVenue = nextSessionCopy(
    {
      occurrence_id: "occ-2",
      session_id: "sess-1",
      session_title: "Junior Beginners",
      location: null,
      start_at: "2026-09-10T23:00:00Z",
      end_at: "2026-09-11T00:00:00Z",
      coach_name: null,
    },
    "America/Chicago",
  );
  assert.equal(noVenue.where, "Venue to be confirmed");
  assert.equal(nextSessionCopy(null, "America/Chicago"), null);
});

test("milestone copy labels notes and skills with a relative date", () => {
  const now = new Date("2026-09-06T12:00:00Z");
  assert.equal(
    milestoneCopy({ kind: "skill", label: "Backhand lift", at: "2026-09-06T14:00:00Z" }, "America/Chicago", now),
    "Backhand lift · Today",
  );
  assert.equal(
    milestoneCopy({ kind: "note", label: "Footwork is sharper", at: "2026-09-05T14:00:00Z" }, "America/Chicago", now),
    "Footwork is sharper · Yesterday",
  );
  assert.equal(
    milestoneCopy({ kind: "skill", label: "Overhead clear", at: "2026-09-03T14:00:00Z" }, "America/Chicago", now),
    "Overhead clear · 3 days ago",
  );
  assert.equal(
    milestoneCopy({ kind: "note", label: "Great serve", at: "2026-08-20T14:00:00Z" }, "America/Chicago", now),
    "Great serve · Aug 20",
  );
  assert.equal(milestoneCopy(null, "America/Chicago", now), null);
});

test("formats money and progress percentages safely", () => {
  assert.equal(formatMoney(18000, "usd"), "$180.00");
  assert.equal(progressPercent(7, 10), 70);
  assert.equal(progressPercent(0, 0), null);
});
