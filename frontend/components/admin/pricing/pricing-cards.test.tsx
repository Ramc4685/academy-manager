import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it } from "vitest";

import type { PricingClass, PricingPlan, PricingSavedOverride } from "@/lib/api/v2/pricing";

import { ClassPricesCard } from "./class-prices-card";
import { SavedOverridesCard } from "./saved-overrides-card";

// Settings overhaul PR 11b: the Pricing page shows what each class is charged
// (its own fee) and only offers plans at exactly that fee.

const plan = (plan_id: string, price_cents: number): PricingPlan => ({
  plan_id,
  name: plan_id === "group" ? "Group class" : "Private lesson",
  description: null,
  price_cents,
  plan_type: "monthly",
  is_active: true,
  linked_classes: 0,
  updated_at: "2026-09-29T00:00:00Z",
});

const cls = (overrides: Partial<PricingClass>): PricingClass => ({
  session_id: "sess-1",
  title: "Juniors",
  charged_cents: 12_000,
  fee_set: true,
  students: 3,
  plan_id: null,
  matching_plan_ids: [],
  stale_link: false,
  ...overrides,
});

function render(node: React.ReactNode): string {
  return renderToStaticMarkup(
    <QueryClientProvider client={new QueryClient()}>{node}</QueryClientProvider>,
  );
}

describe("ClassPricesCard", () => {
  const plans = [plan("group", 12_000), plan("private", 24_000)];

  it("offers only the plans at the class fee, plus Custom", () => {
    const html = render(
      <ClassPricesCard
        classes={[cls({ plan_id: "group", matching_plan_ids: ["group"] })]}
        plans={plans}
        autoLinkable={0}
      />,
    );
    expect(html).toContain(">Custom<");
    expect(html).toContain(">Group class<");
    expect(html).not.toContain("Private lesson");
    expect(html).toContain("$120.00");
  });

  it("says when no plan has the class price and when a class has no fee", () => {
    const html = render(
      <ClassPricesCard
        classes={[cls({ charged_cents: 0, fee_set: false })]}
        plans={plans}
        autoLinkable={0}
      />,
    );
    expect(html).toContain("No plan has this price.");
    expect(html).toContain("No fee set");
  });

  it("explains a link whose plan price moved away from the fee", () => {
    const html = render(
      <ClassPricesCard classes={[cls({ stale_link: true })]} plans={plans} autoLinkable={0} />,
    );
    expect(html).toContain("Its plan&#x27;s price changed, so it shows as Custom.");
  });

  it("says an archived plan was archived, not that its price changed", () => {
    const html = render(
      <ClassPricesCard
        classes={[cls({ stale_link: true, stale_reason: "archived" })]}
        plans={plans}
        autoLinkable={0}
      />,
    );
    expect(html).toContain("Its plan was archived, so it shows as Custom.");
    expect(html).not.toContain("price changed");
  });

  it("shows a fee a scheduled plan price change will move", () => {
    const html = render(
      <ClassPricesCard
        classes={[cls({ scheduled_cents: 13_000, scheduled_from: "2026-11" })]}
        plans={plans}
        autoLinkable={0}
      />,
    );
    expect(html).toContain("Scheduled: $130.00 from November 2026");
  });

  it("counts the classes Link matching classes would link", () => {
    const html = render(<ClassPricesCard classes={[cls({})]} plans={plans} autoLinkable={2} />);
    expect(html).toContain("2 classes have exactly one plan at the same price");
  });
});

describe("SavedOverridesCard", () => {
  it("shows an empty state when nothing is saved", () => {
    const html = renderToStaticMarkup(<SavedOverridesCard overrides={[]} />);
    expect(html).toContain("No saved overrides");
  });

  it("lists a saved override beside what is actually charged", () => {
    const row: PricingSavedOverride = {
      source: "billing_plan",
      enrollment_id: "bill-1",
      student_id: "st-1",
      student_name: "Ada Lovelace",
      label: "Group class",
      override_cents: 8_000,
      charged_cents: 12_000,
      status: "active",
    };
    const html = renderToStaticMarkup(<SavedOverridesCard overrides={[row]} />);
    expect(html).toContain("Ada Lovelace");
    expect(html).toContain("$80.00");
    expect(html).toContain("$120.00");
    expect(html).toContain("Billing plan override");
  });
});
