import { createElement } from "react";
import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it } from "vitest";

import { BrandLockup } from "./brand-lockup";

function render(props: Parameters<typeof BrandLockup>[0]): string {
  return renderToStaticMarkup(createElement(BrandLockup, props));
}

describe("BrandLockup", () => {
  it("uses a valid hex brand_color as the monogram background on an academy host", () => {
    const html = render({
      tone: "dark",
      academyName: "Riverside Shuttle Club",
      logoUrl: null,
      brandColor: "#1a56db",
    });
    expect(html).toContain("background:#1a56db");
  });

  it("rejects a non-hex brand_color (CSS injection attempt) and falls back to the default", () => {
    const html = render({
      tone: "dark",
      academyName: "Riverside Shuttle Club",
      logoUrl: null,
      brandColor: "url(https://attacker.example/beacon.png)",
    });
    expect(html).not.toContain("attacker.example");
    expect(html).not.toContain("url(");
    expect(html).toContain("background:#facc15");
  });

  it("never uses brand_color on the platform host, even when one is somehow present", () => {
    const html = render({
      tone: "dark",
      academyName: null,
      logoUrl: null,
      brandColor: "url(https://attacker.example/beacon.png)",
    });
    expect(html).not.toContain("attacker.example");
    expect(html).toContain("background:#facc15");
  });
});
