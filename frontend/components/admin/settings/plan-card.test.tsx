import { renderToStaticMarkup } from "react-dom/server";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { describe, expect, it, vi } from "vitest";

vi.mock("@/lib/api/admin", () => ({ getAdminPlan: vi.fn(), startGrowthCheckout: vi.fn() }));
vi.mock("next/navigation", () => ({
  useSearchParams: () => new URLSearchParams(""),
}));

import type { AdminPlanOverview } from "@/lib/api/admin";
import { queryKeys } from "@/lib/query/keys";
import { PlanCard } from "./plan-card";

const GROWTH = { code: "growth", display_name: "Growth", monthly_price_cents: 9900, features: ["ai"] };

function html(overview: AdminPlanOverview) {
  const client = new QueryClient();
  client.setQueryData(queryKeys.admin.plan(), overview);
  return renderToStaticMarkup(
    <QueryClientProvider client={client}>
      <PlanCard />
    </QueryClientProvider>,
  );
}

describe("PlanCard", () => {
  it("shows the free plan and the Growth upgrade when checkout is open", () => {
    const out = html({ plan: null, subscription: null, growth: GROWTH, checkout_available: true });
    expect(out).toContain("Free (core operations)");
    expect(out).toContain("Growth · $99 a month");
    expect(out).toContain("0 bps processing markup");
    expect(out).toContain("AI features");
    expect(out).toContain("Upgrade to Growth");
  });

  it("explains when checkout is unavailable instead of offering a button", () => {
    const out = html({ plan: null, subscription: null, growth: null, checkout_available: false });
    expect(out).toContain("Growth checkout is not open yet");
    expect(out).not.toContain("Upgrade to Growth");
  });

  it("shows the active Growth plan and hides the pitch", () => {
    const out = html({
      plan: GROWTH,
      subscription: { billing_status: "active", cancel_at_period_end: false, current_period_end: null },
      growth: GROWTH,
      checkout_available: true,
    });
    expect(out).toContain("Growth · $99 a month");
    expect(out).toContain("Active");
    expect(out).not.toContain("Upgrade to Growth");
  });
});
