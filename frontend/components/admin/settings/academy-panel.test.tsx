import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it } from "vitest";

import { queryKeys } from "@/lib/query/keys";
import type { AdminAcademyView } from "@/lib/api/admin";

import { AcademyPanel, invoicePrefixHint } from "./academy-panel";

describe("invoicePrefixHint (Settings overhaul P1 PR 2)", () => {
  it("shows what an invoice number looks like with the academy's prefix", () => {
    expect(invoicePrefixHint("BLNO")).toBe(
      "Invoice numbers look like BLNO-2026-09-0001. Set by CourtMastr.",
    );
  });

  it("says the prefix is not set rather than inventing one", () => {
    expect(invoicePrefixHint(null)).toMatch(/Not set yet/);
    expect(invoicePrefixHint("")).not.toMatch(/BLNO/);
  });
});

function renderPanel(data?: Partial<AdminAcademyView>): string {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  client.setQueryData(queryKeys.admin.academy(), {
    academy_id: "acad",
    display_name: "Court 7",
    timezone: "America/Chicago",
    contact_email: null,
    contact_phone: null,
    hours_text: null,
    address: null,
    currency: "USD",
    invoice_prefix: "BLNO",
    ...data,
  });
  return renderToStaticMarkup(
    <QueryClientProvider client={client}>
      <AcademyPanel />
    </QueryClientProvider>,
  );
}

describe("AcademyPanel currency (Settings overhaul P1 PR 3)", () => {
  it("shows currency as a read-only USD field, not a select", () => {
    const html = renderPanel();

    expect(html).toContain('data-testid="academy-currency"');
    expect(html).toContain('value="USD"');
    expect(html).toContain("readOnly");
    expect(html).toContain("Set by CourtMastr. All charges are in US dollars.");
    expect(html).not.toContain("CAD — Canadian Dollar");
  });

  it("still shows the read-only invoice prefix alongside it", () => {
    const html = renderPanel();

    expect(html).toContain('data-testid="academy-invoice-prefix"');
    expect(html).toContain('value="BLNO"');
  });
});
