import { describe, expect, it } from "vitest";

import type { AdminCollectionsFamily, CollectionsBucketKey } from "@/lib/api/admin";

import {
  ACTION_LABEL,
  BUCKET_META,
  BUCKET_ORDER,
  daysBetween,
  familyChip,
  normalizeCollections,
  secondaryLine,
  studentLine,
} from "./bucket-view";

const TODAY = "2026-09-10";

function family(overrides: Partial<AdminCollectionsFamily> = {}): AdminCollectionsFamily {
  return {
    parent_id: "par_1",
    parent_name: "Priya Raman",
    parent_email: "priya@example.com",
    students: [{ student_id: "stu_1", name: "Hannah", session_title: "Wed 6:15 Intermediate" }],
    invoices: [
      {
        invoice_id: "inv_1",
        invoice_number: "INV-0001",
        period: "2026-09",
        status: "open",
        total_cents: 18500,
        balance_due_cents: 18500,
        due_date: "2026-09-08",
        delivery_status: "sent",
      },
    ],
    balance_cents: 18500,
    leftover_balance_cents: 0,
    autopay: null,
    failure: null,
    pause: null,
    paid: null,
    last_reminder_at: null,
    actions: [],
    ...overrides,
  };
}

describe("BUCKET_ORDER / BUCKET_META / ACTION_LABEL", () => {
  it("lists the six buckets in spec order", () => {
    expect(BUCKET_ORDER).toEqual([
      "failed_autopay",
      "past_due",
      "awaiting",
      "autopay_scheduled",
      "paused",
      "paid",
    ]);
  });

  it("has a title, hint, stripe and empty line for every bucket", () => {
    for (const key of BUCKET_ORDER) {
      const meta = BUCKET_META[key];
      expect(meta.title.length).toBeGreaterThan(0);
      expect(meta.hint.length).toBeGreaterThan(0);
      expect(meta.stripe).toMatch(/^bg-/);
      expect(meta.emptyLine).toMatch(/^No /);
    }
    expect(BUCKET_META.failed_autopay.title).toBe("Failed autopay");
    expect(BUCKET_META.past_due.title).toBe("Past due");
    expect(BUCKET_META.awaiting.title).toBe("Awaiting payment");
    expect(BUCKET_META.autopay_scheduled.title).toBe("Autopay scheduled");
    expect(BUCKET_META.paused.title).toBe("Paused");
    expect(BUCKET_META.paid.title).toBe("Paid");
    expect(BUCKET_META.failed_autopay.emptyLine).toBe("No failed autopay");
  });

  it("labels all five actions", () => {
    expect(ACTION_LABEL).toEqual({
      send_reminder: "Send reminder",
      record_payment: "Record payment",
      message: "Message",
      skip_month: "Skip this month",
      resume: "Resume",
    });
  });
});

describe("normalizeCollections", () => {
  it("returns zero totals and six empty buckets for undefined", () => {
    const view = normalizeCollections(undefined);
    expect(view.totals).toEqual({
      owed_cents: 0,
      autopay_scheduled_cents: 0,
      autopay_scheduled_count: 0,
      needs_action_count: 0,
      collected_cents: 0,
    });
    expect(view.buckets.map((b) => b.key)).toEqual(BUCKET_ORDER);
    for (const bucket of view.buckets) {
      expect(bucket.count).toBe(0);
      expect(bucket.total_cents).toBe(0);
      expect(bucket.families).toEqual([]);
    }
  });

  it("tolerates the legacy payments stub shape { payments: [] }", () => {
    const view = normalizeCollections({ payments: [] });
    expect(view.buckets).toHaveLength(6);
    expect(view.totals.owed_cents).toBe(0);
    expect(typeof view.period).toBe("string");
  });

  it("sorts real buckets into BUCKET_ORDER and fills the missing ones", () => {
    const view = normalizeCollections({
      period: "2026-09",
      generated_at: "2026-09-10T12:00:00Z",
      timezone: "America/Chicago",
      totals: {
        owed_cents: 100,
        autopay_scheduled_cents: 200,
        autopay_scheduled_count: 1,
        needs_action_count: 2,
        collected_cents: 300,
      },
      buckets: [
        { key: "paid", count: 1, total_cents: 300, families: [family()] },
        { key: "failed_autopay", count: 1, total_cents: 100, families: [family()] },
      ],
    });
    expect(view.buckets.map((b) => b.key)).toEqual(BUCKET_ORDER);
    expect(view.buckets[0].count).toBe(1);
    expect(view.buckets[5].count).toBe(1);
    expect(view.buckets[1].families).toEqual([]);
    expect(view.totals.collected_cents).toBe(300);
    expect(view.period).toBe("2026-09");
  });
});

describe("daysBetween", () => {
  it("counts whole calendar days, signed", () => {
    expect(daysBetween("2026-09-08", "2026-09-10")).toBe(2);
    expect(daysBetween("2026-09-10", "2026-09-08")).toBe(-2);
    expect(daysBetween("2026-08-31", "2026-09-01")).toBe(1);
  });
});

describe("studentLine", () => {
  it("joins students with their class", () => {
    expect(studentLine(family())).toBe("Hannah · Wed 6:15 Intermediate");
    expect(
      studentLine(
        family({
          students: [
            { student_id: "a", name: "Hannah", session_title: "Wed 6:15 Intermediate" },
            { student_id: "b", name: "Arjun", session_title: null },
          ],
        }),
      ),
    ).toBe("Hannah · Wed 6:15 Intermediate, Arjun");
  });
});

describe("familyChip", () => {
  it("failed autopay → FAILED, or DISABLED after the ladder", () => {
    const active = family({
      failure: { reason: "card_declined", attempt_count: 2, max_attempts: 4, next_retry_on: "2026-09-12", disabled: false },
    });
    expect(familyChip("failed_autopay", active)).toEqual({ variant: "failed", label: "FAILED" });
    const disabled = family({
      failure: { reason: "card_declined", attempt_count: 4, max_attempts: 4, next_retry_on: null, disabled: true },
    });
    expect(familyChip("failed_autopay", disabled)).toEqual({ variant: "failed", label: "DISABLED" });
  });

  it("past due → N DAYS LATE", () => {
    const chip = familyChip("past_due", family(), TODAY);
    expect(chip.variant).toBe("overdue");
    expect(chip.label).toBe("2 DAYS LATE");
    expect(familyChip("past_due", family({ invoices: [{ ...family().invoices[0], due_date: "2026-09-09" }] }), TODAY).label).toBe(
      "1 DAY LATE",
    );
  });

  it("awaiting → DUE IN N DAYS, with autopay flags", () => {
    const soon = family({ invoices: [{ ...family().invoices[0], due_date: "2026-09-15" }] });
    expect(familyChip("awaiting", soon, TODAY)).toEqual({ variant: "pending", label: "DUE IN 5 DAYS" });
    expect(familyChip("awaiting", family({ invoices: [{ ...family().invoices[0], due_date: TODAY }] }), TODAY).label).toBe(
      "DUE TODAY",
    );
    const noCard = family({
      autopay: { status: "no_card_on_file", card_last4: null, charge_on: null, notice_sent_at: null },
    });
    expect(familyChip("awaiting", noCard, TODAY)).toEqual({ variant: "pending", label: "NO CARD ON FILE" });
    for (const status of ["card_state_unknown", "connected_account_unknown"]) {
      const unknown = family({ autopay: { status, card_last4: null, charge_on: null, notice_sent_at: null } });
      expect(familyChip("awaiting", unknown, TODAY).label).toBe("AUTOPAY STATUS UNAVAILABLE");
    }
  });

  it("autopay scheduled / paused / paid use their own variants", () => {
    expect(familyChip("autopay_scheduled", family())).toEqual({ variant: "autopayOn", label: "AUTOPAY" });
    expect(familyChip("paused", family())).toEqual({ variant: "paused", label: "PAUSED" });
    expect(familyChip("paid", family())).toEqual({ variant: "paid", label: "PAID" });
  });
});

describe("secondaryLine", () => {
  it("failed: attempt count and next retry, or no more retries", () => {
    const retrying = family({
      failure: { reason: "card_declined", attempt_count: 2, max_attempts: 4, next_retry_on: "2026-09-12", disabled: false },
    });
    const line = secondaryLine("failed_autopay", retrying, TODAY);
    expect(line).toContain("card declined");
    expect(line).toContain("attempt 2 of 4");
    expect(line).toContain("retries Sep 12, 2026");

    const exhausted = family({
      failure: { reason: null, attempt_count: 4, max_attempts: 4, next_retry_on: null, disabled: true },
    });
    expect(secondaryLine("failed_autopay", exhausted, TODAY)).toBe("attempt 4 of 4 · no more retries");
  });

  it("past due: due date, days late, reminder state, months owed", () => {
    expect(secondaryLine("past_due", family(), TODAY)).toBe("due Sep 8, 2026 · 2 days late · never reminded");
    const reminded = family({ last_reminder_at: "2026-09-09T15:00:00Z", leftover_balance_cents: 5000 });
    expect(secondaryLine("past_due", reminded, TODAY)).toBe(
      "due Sep 8, 2026 · 2 days late · reminded Sep 9, 2026 · 2 months owed",
    );
  });

  it("awaiting: due date and delivery state", () => {
    expect(
      secondaryLine(
        "awaiting",
        family({ invoices: [{ ...family().invoices[0], due_date: "2026-09-15", delivery_status: "sent" }] }),
        TODAY,
      ),
    ).toBe("due Sep 15, 2026 · invoice emailed");
    expect(
      secondaryLine(
        "awaiting",
        family({ invoices: [{ ...family().invoices[0], due_date: "2026-09-15", delivery_status: "not_sent" }] }),
        TODAY,
      ),
    ).toBe("due Sep 15, 2026 · invoice not sent");
  });

  it("autopay scheduled: card, charge time, notice", () => {
    const scheduled = family({
      autopay: { status: "eligible", card_last4: "4242", charge_on: "2026-09-15", notice_sent_at: "2026-09-08T09:00:00Z" },
    });
    expect(secondaryLine("autopay_scheduled", scheduled, TODAY)).toBe(
      "card ••4242 · charges Sep 15, 2026 9:00 AM · notice emailed Sep 8, 2026",
    );
    const noNotice = family({
      autopay: { status: "eligible", card_last4: "4242", charge_on: "2026-09-15", notice_sent_at: null },
    });
    expect(secondaryLine("autopay_scheduled", noNotice, TODAY)).toBe(
      "card ••4242 · charges Sep 15, 2026 9:00 AM · notice not sent",
    );
  });

  it("paused: class, resume/review date, leftover", () => {
    const paused = family({
      invoices: [],
      balance_cents: 0,
      pause: { enrollment_id: "enr_1", resume_on: "2026-10-01", review_on: null, session_title: "Wed 6:15 Intermediate", student_name: "Hannah" },
    });
    expect(secondaryLine("paused", paused, TODAY)).toBe("Wed 6:15 Intermediate · resumes Oct 1, 2026 · no balance");
    const review = family({
      invoices: [],
      leftover_balance_cents: 4500,
      pause: { enrollment_id: "enr_1", resume_on: null, review_on: "2026-09-20", session_title: null, student_name: "Hannah" },
    });
    expect(secondaryLine("paused", review, TODAY)).toBe("Hannah · review Sep 20, 2026 · leftover $45.00");
  });

  it("paid: method and date", () => {
    const paid = family({ paid: { amount_cents: 18500, method: "stripe_autopay", paid_at: "2026-09-08T14:00:00Z" } });
    expect(secondaryLine("paid", paid, TODAY)).toBe("Stripe · Sep 8, 2026");
    const cash = family({ paid: { amount_cents: 18500, method: "cash", paid_at: null } });
    expect(secondaryLine("paid", cash, TODAY)).toBe("Cash · —");
  });

  it("never throws on a family with no detail block", () => {
    for (const key of BUCKET_ORDER as CollectionsBucketKey[]) {
      expect(() => secondaryLine(key, family({ invoices: [] }), TODAY)).not.toThrow();
    }
  });
});
