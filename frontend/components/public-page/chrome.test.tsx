import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it } from "vitest";

import { SiteFooter } from "./chrome";

describe("SiteFooter legal links (Settings overhaul Phase 4 PR 13)", () => {
  it("keeps today's footer when the academy set no legal links", () => {
    const html = renderToStaticMarkup(<SiteFooter privacyUrl={null} supportEmail={null} />);
    expect(html).toContain('href="/terms"');
    expect(html).toContain('href="/privacy"');
    expect(html).not.toContain("Refund policy");
  });

  it("shows the academy's terms and refund links when set", () => {
    const html = renderToStaticMarkup(
      <SiteFooter
        privacyUrl="https://blno.example/privacy"
        termsUrl="https://blno.example/terms"
        refundUrl="https://blno.example/refunds"
        supportEmail="help@blno.example"
      />,
    );
    expect(html).toContain('href="https://blno.example/terms"');
    expect(html).toContain('href="https://blno.example/refunds"');
    expect(html).toContain('href="https://blno.example/privacy"');
    expect(html).toContain("mailto:help@blno.example");
    expect(html).not.toContain('href="/terms"');
  });

  it("never renders a non-https legal link", () => {
    const html = renderToStaticMarkup(
      <SiteFooter termsUrl="javascript:alert(1)" refundUrl="http://blno.example/refunds" />,
    );
    expect(html).not.toContain("javascript:");
    expect(html).not.toContain("Refund policy");
    expect(html).toContain('href="/terms"');
  });
});
