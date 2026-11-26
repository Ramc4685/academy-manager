import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it } from "vitest";

import {
  ShowOnPublicPageSwitch,
  defaultShowOnPublicPage,
  parentPreviewHref,
  showOnPublicPageHint,
} from "./class-public-page";

describe("class public page controls (S55)", () => {
  it("starts a new class shown only once the academy page is published (D-22)", () => {
    expect(defaultShowOnPublicPage(true)).toBe(true);
    expect(defaultShowOnPublicPage(false)).toBe(false);
    expect(defaultShowOnPublicPage(undefined)).toBe(false);
  });

  it("says nobody sees the class while the page is unpublished", () => {
    expect(showOnPublicPageHint(false)).toMatch(/not published yet/);
    expect(showOnPublicPageHint(true)).toMatch(/^Anyone visiting/);
  });

  it("previews the academy's own page at its classes", () => {
    expect(parentPreviewHref("https://riverside.example.test/", null)).toBe(
      "https://riverside.example.test/#classes",
    );
    expect(
      parentPreviewHref(null, { origin: "http://demo-academy.localhost:3001", host: "demo-academy.localhost:3001" }),
    ).toBe("http://demo-academy.localhost:3001/#classes");
    expect(parentPreviewHref(null, null)).toBeNull();
  });

  it("renders an accessible switch", () => {
    const html = renderToStaticMarkup(
      <ShowOnPublicPageSwitch checked pagePublished onChange={() => {}} />,
    );
    expect(html).toContain('role="switch"');
    expect(html).toContain("Show on public page");
    expect(html).toContain('data-testid="class-show-on-public-page"');
    expect(html).toContain("checked");
  });
});
