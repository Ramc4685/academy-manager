import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it } from "vitest";

import { queryKeys } from "@/lib/query/keys";
import type { BillingIdentity } from "@/lib/api/platform";

import { BillingIdentityCard } from "./billing-identity-card";

function renderCard(identity: BillingIdentity, canEdit = true): string {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  client.setQueryData(queryKeys.platform.tenantBillingIdentity(identity.academy_id), identity);
  return renderToStaticMarkup(
    <QueryClientProvider client={client}>
      <BillingIdentityCard academyId={identity.academy_id} canEdit={canEdit} />
    </QueryClientProvider>,
  );
}

describe("BillingIdentityCard (Settings overhaul P1 PR 3)", () => {
  it("shows the invoice prefix and USD currency, editable when unlocked", () => {
    const html = renderCard({ academy_id: "acad", invoice_prefix: "BLNO", locked: false });

    expect(html).toContain('data-testid="billing-identity-prefix"');
    expect(html).toContain("BLNO");
    expect(html).toContain("USD");
    expect(html).toContain("Change prefix");
    expect(html).not.toContain('data-testid="billing-identity-locked"');
  });

  it("goes read-only with the reason once the endpoint reports it locked", () => {
    const html = renderCard({ academy_id: "acad", invoice_prefix: "BLNO", locked: true });

    expect(html).toContain('data-testid="billing-identity-locked"');
    expect(html).toMatch(/numbered invoice/);
    expect(html).not.toContain("Change prefix");
  });

  it("renders nothing for a persona without edit access", () => {
    const html = renderCard({ academy_id: "acad", invoice_prefix: "BLNO", locked: false }, false);

    expect(html).toBe("");
  });
});
