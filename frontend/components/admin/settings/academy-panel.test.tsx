import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it } from "vitest";

import { queryKeys } from "@/lib/query/keys";
import type { AdminAcademyView } from "@/lib/api/admin";

import {
  AcademyPanel,
  httpsLinkError,
  invoicePrefixHint,
  replyToHint,
  supportEmailError,
} from "./academy-panel";

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

describe("AcademyPanel class defaults (Settings overhaul Phase 3 PR 9)", () => {
  it("has a Class defaults card seeded 10 / 45 before the academy resolves", () => {
    const html = renderPanel();

    expect(html).toContain("Class defaults");
    expect(html).toContain("Default class size");
    expect(html).toContain("Default class length (minutes)");
    // Two number inputs seeded 10 and 45 (class size, class length) — the
    // form's initial state, since read data only lands via a client effect.
    expect(html).toContain('value="10"');
    expect(html).toContain('value="45"');
  });
});

describe("AcademyPanel brand preview (Settings overhaul Phase 3 PR 9)", () => {
  it("never hardcodes a different academy's name in the preview", () => {
    const html = renderPanel({ display_name: "Court 7" });

    expect(html).toContain("Court 7");
    expect(html).not.toContain("Rally Academy");
  });
});

describe("Academy profile tab (Settings overhaul Phase 3 PR 9)", () => {
  it("is labelled for the merged Academy + Branding tab", () => {
    const html = renderPanel();

    expect(html).toContain('data-testid="admin-settings-academy"');
    expect(html).toContain('aria-label="Academy profile tab"');
  });
});

describe("AcademyPanel support email and legal links (Settings overhaul Phase 4 PR 13)", () => {
  it("has a Support email field in Contact & location and a Legal links card", () => {
    const html = renderPanel();

    expect(html).toContain("Support email for parents");
    expect(html).toContain('data-testid="academy-legal-links"');
    expect(html).toContain("Terms of service");
    expect(html).toContain("Refund policy");
    expect(html).toContain("Privacy notice");
    // Card order: Contact & location, Brand, Class defaults, Legal links.
    const order = ["Contact &amp; location", ">Brand<", "Class defaults", "Legal links"].map((t) =>
      html.indexOf(t),
    );
    expect(order.every((i) => i >= 0)).toBe(true);
    expect([...order].sort((a, b) => a - b)).toEqual(order);
  });

  it("says the reply-to defaults to the support email", () => {
    expect(replyToHint("")).toContain("Defaults to the support email");
    expect(replyToHint(" help@blno.example ")).toContain("use the support email (help@blno.example)");
    expect(renderPanel()).toContain("Defaults to the support email");
  });
});

describe("httpsLinkError", () => {
  it.each(["", "  ", "https://blno.example/terms"])("accepts %j", (value) =>
    expect(httpsLinkError(value)).toBeNull(),
  );

  it.each([
    "http://blno.example/terms",
    "javascript:alert(1)",
    "data:text/html,hi",
    "ftp://blno.example/x",
    "blno.example/terms",
    "mailto:a@b.co",
  ])("rejects %j", (value) => expect(httpsLinkError(value)).not.toBeNull());
});

describe("supportEmailError", () => {
  it.each(["", "  ", "help@blno.example"])("accepts %j", (value) =>
    expect(supportEmailError(value)).toBeNull(),
  );
  it.each(["help", "help@", "a b@c.co"])("rejects %j", (value) =>
    expect(supportEmailError(value)).not.toBeNull(),
  );
});
