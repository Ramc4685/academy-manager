import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it } from "vitest";

import {
  billingMonthsFrom,
  formatBillingMonth,
  type PlanPriceChangePreview,
  type PricingPlan,
} from "@/lib/api/v2/pricing";

import { ChangePlanPriceCard, PriceChangePreview } from "./change-plan-price-card";

// Settings overhaul PR 26: change a plan price with a preview, from a month.

const preview: PlanPriceChangePreview = {
  plan_id: "group",
  plan_name: "Group class",
  old_cents: 12_000,
  new_cents: 13_000,
  effective_period: "2026-11",
  earliest_period: "2026-11",
  classes: [
    {
      session_id: "a",
      title: "Juniors Tue/Thu",
      students: 14,
      old_cents: 12_000,
      new_cents: 13_000,
    },
    { session_id: "b", title: "Adults Sat", students: 9, old_cents: 12_000, new_cents: 13_000 },
  ],
  not_affected: [
    { session_id: "c", title: "Competitive squad", charged_cents: 12_000, students: 6 },
  ],
  total_classes: 2,
  total_students: 23,
  old_monthly_cents: 276_000,
  new_monthly_cents: 299_000,
};

const plan = (overrides: Partial<PricingPlan>): PricingPlan => ({
  plan_id: "group",
  name: "Group class",
  description: null,
  price_cents: 12_000,
  plan_type: "monthly",
  is_active: true,
  linked_classes: 2,
  updated_at: "2026-09-29T00:00:00Z",
  ...overrides,
});

function render(node: React.ReactNode): string {
  return renderToStaticMarkup(
    <QueryClientProvider client={new QueryClient()}>{node}</QueryClientProvider>,
  );
}

describe("PriceChangePreview", () => {
  it("says who is affected, from which invoice, and that sent invoices never change", () => {
    const html = renderToStaticMarkup(<PriceChangePreview preview={preview} />);
    expect(html).toContain("2 classes, 23 students affected, from the <b>November</b> invoice");
    expect(html).toContain("Invoices already sent never change.");
    expect(html).toContain("Juniors Tue/Thu");
    expect(html).toContain("$2,990.00");
    expect(html).toContain("Not affected (custom price): Competitive squad.");
  });

  it("explains a plan with no linked class", () => {
    const html = renderToStaticMarkup(
      <PriceChangePreview
        preview={{ ...preview, classes: [], total_classes: 0, total_students: 0 }}
      />,
    );
    expect(html).toContain("No class is linked to this plan, so no bill changes.");
  });
});

describe("ChangePlanPriceCard", () => {
  it("lists a scheduled change with a cancel button and hides its plan from the picker", () => {
    const html = render(
      <ChangePlanPriceCard
        plans={[
          plan({
            scheduled_change_id: "ppc-1",
            scheduled_cents: 13_000,
            scheduled_from: "2026-11",
          }),
          plan({ plan_id: "private", name: "Private lesson", price_cents: 24_000 }),
        ]}
      />,
    );
    expect(html).toContain("from the November 2026 invoice");
    expect(html).toContain("Cancel change");
    expect(html).toContain("Private lesson ($240.00)");
    expect(html).not.toContain("Group class ($120.00)");
  });
});

describe("billing month helpers", () => {
  it("names months and rolls over the year", () => {
    expect(formatBillingMonth("2026-11")).toBe("November");
    expect(formatBillingMonth("2027-01", { year: true })).toBe("January 2027");
    expect(billingMonthsFrom("2026-11", 3)).toEqual(["2026-11", "2026-12", "2027-01"]);
  });
});
