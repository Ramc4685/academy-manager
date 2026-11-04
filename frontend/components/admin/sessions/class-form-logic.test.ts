import { describe, expect, it } from "vitest";

import type { AdminSessionView } from "@/lib/api/admin";
import type { PricingPlan } from "@/lib/api/v2/pricing";

import {
  CUSTOM_PRICE,
  EMPTY_WELCOME_EMAIL,
  academyDefaultPlaceholder,
  addMinutesToTime,
  buildClassEditPayload,
  classFormFromSession,
  feeForChoice,
  initialPriceChoice,
  pickablePlans,
  planLinkToWrite,
  planOptionLabel,
  priceChanges,
  welcomeEmailPayload,
} from "./class-form-logic";

function plan(overrides: Partial<PricingPlan> = {}): PricingPlan {
  return {
    plan_id: "plan-group",
    name: "Group class",
    description: null,
    price_cents: 6000,
    plan_type: "monthly",
    is_active: true,
    linked_classes: 1,
    updated_at: "2026-09-01T00:00:00Z",
    ...overrides,
  };
}

const PLANS = [
  plan(),
  plan({ plan_id: "plan-private", name: "Private", price_cents: 12050 }),
  plan({ plan_id: "plan-old", name: "Old plan", price_cents: 5000, is_active: false }),
];

const PACK = {
  whatsapp_group_link: "https://chat.whatsapp.com/AbCd1234",
  venue_address: "12 Court Lane",
  parking_notes: "Free lot",
  what_to_bring: "Racquet",
  arrival_minutes_before: 15,
  coach_contact_policy: "Message in the app",
  absence_policy: "Tell us 24h ahead",
};

function session(overrides: Partial<AdminSessionView> = {}): AdminSessionView {
  return {
    session_id: "sess-1",
    coach_id: "coach-1",
    title: "Beginner",
    location: "YWCA",
    start_at: "2026-10-01T22:45:00Z",
    end_at: "2026-10-01T23:30:00Z",
    days_of_week: ["Wed"],
    start_time: "17:45",
    end_time: "18:30",
    timezone: "America/Chicago",
    capacity: 16,
    amount_cents: 6000,
    enrolled_count: 12,
    waitlist_count: 0,
    ...PACK,
    ...overrides,
  } as AdminSessionView;
}

const PACK_KEYS = Object.keys(PACK);

describe("plan picker", () => {
  it("offers active plans only, labelled with their price per month", () => {
    const options = pickablePlans(PLANS);
    expect(options.map((p) => p.plan_id)).toEqual(["plan-group", "plan-private"]);
    expect(planOptionLabel(options[0])).toBe("Group class · $60 / month");
    expect(planOptionLabel(options[1])).toBe("Private · $120.50 / month");
  });

  it("starts at the class's linked plan, or Custom when unlinked or stale", () => {
    expect(initialPriceChoice({ plan_id: "plan-group" }, PLANS)).toBe("plan-group");
    expect(initialPriceChoice({ plan_id: null }, PLANS)).toBe(CUSTOM_PRICE);
    expect(initialPriceChoice(undefined, PLANS)).toBe(CUSTOM_PRICE);
    // An archived plan is not offered, so its link reads Custom.
    expect(initialPriceChoice({ plan_id: "plan-old" }, PLANS)).toBe(CUSTOM_PRICE);
  });

  it("sets the fee to the picked plan's price, or the typed fee for Custom", () => {
    expect(feeForChoice("plan-private", PLANS, 999)).toBe(12050);
    expect(feeForChoice(CUSTOM_PRICE, PLANS, 7500)).toBe(7500);
    expect(feeForChoice(CUSTOM_PRICE, PLANS, null)).toBeNull();
  });

  it("writes a link only when the choice changed; Custom unlinks", () => {
    expect(planLinkToWrite("plan-group", "plan-group")).toBeUndefined();
    expect(planLinkToWrite(CUSTOM_PRICE, "plan-group")).toBe("plan-group");
    expect(planLinkToWrite("plan-group", CUSTOM_PRICE)).toBeNull();
    expect(planLinkToWrite(CUSTOM_PRICE, CUSTOM_PRICE)).toBeUndefined();
  });
});

describe("buildClassEditPayload", () => {
  it("never sends a welcome-email (communication pack) field", () => {
    const stored = session();
    const payload = buildClassEditPayload({
      session: stored,
      values: { ...classFormFromSession(stored), title: "Beginner B" },
      isOwner: true,
    });
    for (const key of PACK_KEYS) expect(payload).not.toHaveProperty(key);
    expect(payload.title).toBe("Beginner B");
  });

  it("sends no fee and no reason when the price does not change", () => {
    const stored = session();
    const payload = buildClassEditPayload({
      session: stored,
      values: { ...classFormFromSession(stored), capacity: 18, reason: "typed anyway" },
      isOwner: true,
    });
    expect(payload).not.toHaveProperty("amount_cents");
    expect(payload).not.toHaveProperty("reason");
    expect(payload.capacity).toBe(18);
  });

  it("sends the new fee and the reason when an owner changes the price", () => {
    const stored = session();
    const payload = buildClassEditPayload({
      session: stored,
      values: { ...classFormFromSession(stored), amount_cents: 12050, reason: " New term " },
      isOwner: true,
    });
    expect(payload.amount_cents).toBe(12050);
    expect(payload.reason).toBe("New term");
  });

  it("never sends a fee for a non-owner", () => {
    const stored = session();
    const payload = buildClassEditPayload({
      session: stored,
      values: { ...classFormFromSession(stored), amount_cents: 1 },
      isOwner: false,
    });
    expect(payload).not.toHaveProperty("amount_cents");
  });

  it("sends an unpriced class's null fee back unchanged, so the percent-pay guard still runs", () => {
    // Review finding: the backend only checks "percent-paid coach needs a
    // price" when a null fee is sent. A coach change on an unpriced class
    // must still carry it, for owners and admins alike.
    const stored = session({ amount_cents: null });
    for (const isOwner of [true, false]) {
      const payload = buildClassEditPayload({
        session: stored,
        values: { ...classFormFromSession(stored), coach_id: "coach-percent", reason: "x" },
        isOwner,
      });
      expect(payload).toHaveProperty("amount_cents", null);
      expect(payload).not.toHaveProperty("reason");
      expect(payload.coach_id).toBe("coach-percent");
    }
  });

  it("sends a one-off class's date back unchanged", () => {
    const stored = session({ days_of_week: [], start_time: null, end_time: null });
    const payload = buildClassEditPayload({
      session: stored,
      values: classFormFromSession(stored),
      isOwner: false,
    });
    expect(payload.start_at).toBe(stored.start_at);
    expect(payload.end_at).toBe(stored.end_at);
    expect(payload.days_of_week).toEqual([]);
  });

  it("treats null and undefined fees as the same price", () => {
    expect(priceChanges(null, undefined)).toBe(false);
    expect(priceChanges(6000, 6000)).toBe(false);
    expect(priceChanges(6000, null)).toBe(true);
  });
});

describe("welcome email at create", () => {
  it("sends only the fields the admin typed", () => {
    expect(welcomeEmailPayload(EMPTY_WELCOME_EMAIL)).toEqual({});
    expect(
      welcomeEmailPayload({
        ...EMPTY_WELCOME_EMAIL,
        whatsapp_group_link: " https://chat.whatsapp.com/X ",
        parking_notes: "   ",
        arrival_minutes_before: "10",
      }),
    ).toEqual({
      whatsapp_group_link: "https://chat.whatsapp.com/X",
      arrival_minutes_before: 10,
    });
  });

  it("clamps arrival minutes to the server's 0-120 range", () => {
    expect(
      welcomeEmailPayload({ ...EMPTY_WELCOME_EMAIL, arrival_minutes_before: "500" }),
    ).toEqual({ arrival_minutes_before: 120 });
  });

  it("shows the academy default as a placeholder, or nothing", () => {
    expect(academyDefaultPlaceholder("123 Court St")).toBe("Uses academy default: 123 Court St");
    expect(academyDefaultPlaceholder("  ")).toBe("");
    expect(academyDefaultPlaceholder(null)).toBe("");
  });
});

describe("addMinutesToTime", () => {
  it("adds the academy class length and wraps past midnight", () => {
    expect(addMinutesToTime("18:00", 45)).toBe("18:45");
    expect(addMinutesToTime("23:30", 45)).toBe("00:15");
    expect(addMinutesToTime("", 45)).toBe("");
  });
});
