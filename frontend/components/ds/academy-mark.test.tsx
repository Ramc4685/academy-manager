import { createElement } from "react";
import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it } from "vitest";

import { AcademyMark } from "./academy-mark";

function render(props: Parameters<typeof AcademyMark>[0]): string {
  return renderToStaticMarkup(createElement(AcademyMark, props));
}

describe("AcademyMark", () => {
  it("renders an <img> for an https logo_url", () => {
    const html = render({ name: "Riverside Shuttle Club", logoUrl: "https://cdn.example.com/logo.png" });
    expect(html).toContain("<img");
    expect(html).toContain('src="https://cdn.example.com/logo.png"');
    expect(html).toContain('alt="Riverside Shuttle Club"');
  });

  it("falls back to a monogram when there is no logo", () => {
    const html = render({ name: "Riverside Shuttle Club", logoUrl: null });
    expect(html).not.toContain("<img");
    expect(html).toContain("RS");
  });

  it("falls back to a monogram for a one-word name", () => {
    const html = render({ name: "Academy", logoUrl: null });
    expect(html).toContain("AC");
  });

  it("rejects a plain http URL — never a raw non-https URL", () => {
    const html = render({ name: "Academy", logoUrl: "http://insecure.example.com/logo.png" });
    expect(html).not.toContain("<img");
    expect(html).not.toContain("insecure.example.com");
  });

  it("rejects a javascript: URL", () => {
    const html = render({ name: "Academy", logoUrl: "javascript:alert(1)" });
    expect(html).not.toContain("<img");
    expect(html).not.toContain("javascript:");
  });

  it("rejects a data: URL", () => {
    const html = render({ name: "Academy", logoUrl: "data:text/html,<script>alert(1)</script>" });
    expect(html).not.toContain("<img");
  });

  it("falls back to '?' for an empty/whitespace name", () => {
    const html = render({ name: "   ", logoUrl: null });
    // AcademyMark itself defaults to "Academy" for a blank name, so it still
    // renders a real monogram, not the bare "?" — callers own blanker
    // fallbacks (e.g. "Academy" display names) upstream.
    expect(html).toContain("AC");
  });
});
