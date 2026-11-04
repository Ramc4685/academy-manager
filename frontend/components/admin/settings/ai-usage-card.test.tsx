import { renderToStaticMarkup } from "react-dom/server";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { describe, expect, it, vi } from "vitest";

vi.mock("@/lib/api/admin", () => ({ getAdminAiUsage: vi.fn() }));

import type { AiUsage } from "@/lib/api/admin";
import { queryKeys } from "@/lib/query/keys";

import { AiUsageCard } from "./ai-usage-card";

function html(usage: AiUsage) {
  const client = new QueryClient();
  client.setQueryData(queryKeys.admin.aiUsage(), usage);
  return renderToStaticMarkup(
    <QueryClientProvider client={client}>
      <AiUsageCard />
    </QueryClientProvider>,
  );
}

describe("AiUsageCard (Phase 2 slice A3)", () => {
  it("shows the meter line without an upgrade prompt below the free cap", () => {
    const out = html({ used: 3, cap: 20, tier: "free", upgrade_suggested: false, month: "2026-11" });
    expect(out).toContain("You have used 3 of 20 AI drafts this month");
    expect(out).not.toContain('data-testid="ai-usage-upgrade"');
  });

  it("adds the soft upgrade link at the free cap", () => {
    const out = html({ used: 20, cap: 20, tier: "free", upgrade_suggested: true, month: "2026-11" });
    expect(out).toContain("You have used 20 of 20 AI drafts this month");
    expect(out).toContain("Upgrade to Growth for unlimited drafts");
    expect(out).toContain('href="/admin/settings?panel=billing-rules"');
  });

  it("labels Growth and never prompts", () => {
    const out = html({ used: 25, cap: 200, tier: "growth", upgrade_suggested: false, month: "2026-11" });
    expect(out).toContain("25 of 200 AI drafts this month (Growth plan)");
    expect(out).not.toContain("Upgrade to Growth");
  });
});
