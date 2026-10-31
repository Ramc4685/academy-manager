import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it } from "vitest";

import type { PricingPlan } from "@/lib/api/v2/pricing";

import {
  ClassFormFields,
  WelcomeEmailFields,
  type ClassFormFieldsProps,
  type PriceFieldProps,
} from "./class-form";
import { CUSTOM_PRICE, EMPTY_WELCOME_EMAIL, type ClassFormValues } from "./class-form-logic";

const PLANS: PricingPlan[] = [
  {
    plan_id: "plan-group",
    name: "Group class",
    description: null,
    price_cents: 6000,
    plan_type: "monthly",
    is_active: true,
    linked_classes: 3,
    updated_at: "2026-09-01T00:00:00Z",
  },
];

const VALUES: ClassFormValues = {
  coach_id: "coach-1",
  title: "Beginner",
  location: "YWCA",
  days_of_week: ["Wed"],
  start_time: "17:45",
  end_time: "18:30",
  timezone: "America/Chicago",
  capacity: 16,
  amount_cents: 6000,
  reason: "",
};

function price(overrides: Partial<PriceFieldProps> = {}): PriceFieldProps {
  return {
    isOwner: true,
    plans: PLANS,
    plansLoading: false,
    choice: "plan-group",
    onChoiceChange: () => {},
    customFee: "60",
    onCustomFeeChange: () => {},
    currentCents: 6000,
    showReason: false,
    reason: "",
    onReasonChange: () => {},
    ...overrides,
  };
}

function render(overrides: Partial<ClassFormFieldsProps> = {}): string {
  return renderToStaticMarkup(
    <ClassFormFields
      mode="edit"
      values={VALUES}
      onChange={() => {}}
      coaches={[]}
      coachesLoading={false}
      price={price()}
      {...overrides}
    />,
  );
}

describe("ClassFormFields", () => {
  it("shows the plan picker with each plan's monthly price and Custom", () => {
    const out = render();
    expect(out).toContain('data-testid="class-form-price"');
    expect(out).toContain("Group class · $60 / month");
    expect(out).toContain("Custom price");
    // A plan is picked, so the fee box stays hidden.
    expect(out).not.toContain('data-testid="session-edit-monthly-fee"');
  });

  it("reveals the monthly fee box for Custom price", () => {
    const out = render({ price: price({ choice: CUSTOM_PRICE, customFee: "75" }) });
    expect(out).toContain('data-testid="session-edit-monthly-fee"');
    expect(out).toContain('value="75"');
  });

  it("uses the create fee test id at create", () => {
    const out = render({
      mode: "create",
      price: price({ choice: CUSTOM_PRICE, customFee: "", currentCents: null }),
    });
    expect(out).toContain('data-testid="create-session-monthly-fee"');
    expect(out).toContain('data-testid="create-session-timezone"');
  });

  it("shows a non-owner the price read-only, with no picker", () => {
    const out = render({ price: price({ isOwner: false, plans: [] }) });
    expect(out).not.toContain('data-testid="class-form-price"');
    expect(out).not.toContain("Monthly fee");
    expect(out).toContain("$60/month");
    expect(out).toContain('data-testid="owner-only-field-note"');
  });

  it("reads Not set for a non-owner when the class has no price", () => {
    const out = render({ price: price({ isOwner: false, plans: [], currentCents: null }) });
    expect(out).toContain("Not set");
  });

  it("asks why only when the price changes", () => {
    expect(render()).not.toContain("Why is the price changing?");
    expect(render({ price: price({ showReason: true }) })).toContain(
      "Why is the price changing?",
    );
  });

  it("keeps the scheduled price note", () => {
    const out = render({
      price: price({ scheduledFee: { new_cents: 6500, effective_period: "2026-11" } }),
    });
    expect(out).toContain('data-testid="session-edit-scheduled-fee"');
    expect(out).toContain("Scheduled: $65 from November 2026");
  });

  it("has no welcome-email (communication pack) fields in the edit form", () => {
    const out = render();
    expect(out).not.toContain("WhatsApp group link");
    expect(out).not.toContain("Communication pack");
    expect(out).not.toContain("Venue address");
  });
});

describe("WelcomeEmailFields", () => {
  it("is collapsed by default", () => {
    const out = renderToStaticMarkup(
      <WelcomeEmailFields values={EMPTY_WELCOME_EMAIL} onChange={() => {}} defaults={{}} />,
    );
    expect(out).toContain("Welcome email (optional)");
    expect(out).not.toContain("WhatsApp group link");
  });

  it("shows the academy defaults as placeholders and leaves the boxes blank", () => {
    const out = renderToStaticMarkup(
      <WelcomeEmailFields
        values={EMPTY_WELCOME_EMAIL}
        onChange={() => {}}
        defaultOpen
        defaults={{
          venue_address: "123 Court St",
          arrival_minutes_before: 10,
          absence_policy: "Report absences in the app.",
        }}
      />,
    );
    expect(out).toContain('placeholder="Uses academy default: 123 Court St"');
    expect(out).toContain('placeholder="Uses academy default: 10 minutes"');
    expect(out).toContain('placeholder="Uses academy default: Report absences in the app."');
    expect(out).not.toContain(">123 Court St<");
  });
});
