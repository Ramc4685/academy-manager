import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it } from "vitest";

import type { AiUsage } from "@/lib/api/admin";
import { queryKeys } from "@/lib/query/keys";

import { AiUsageCard } from "./ai-usage-card";

function renderCard(usage: AiUsage, canEdit = true): string {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  client.setQueryData(queryKeys.platform.tenantAiUsage("acad"), usage);
  return renderToStaticMarkup(
    <QueryClientProvider client={client}>
      <AiUsageCard academyId="acad" canEdit={canEdit} />
    </QueryClientProvider>,
  );
}

describe("platform AiUsageCard (Phase 2 slice A3)", () => {
  it("shows the academy's meter", () => {
    const html = renderCard({ used: 20, cap: 20, tier: "free", upgrade_suggested: true, month: "2026-11" });
    expect(html).toContain('data-testid="platform-ai-usage"');
    expect(html).toContain("You have used 20 of 20 AI drafts this month");
  });

  it("renders nothing for a persona without platform-admin access", () => {
    expect(renderCard({ used: 0, cap: 20, tier: "free", upgrade_suggested: false, month: "2026-11" }, false)).toBe("");
  });
});
