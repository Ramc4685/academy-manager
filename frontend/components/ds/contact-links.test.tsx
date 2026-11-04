import { createElement } from "react";
import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it } from "vitest";

import { PhoneCountryProvider } from "@/lib/phone-country";

import { ContactLinks, contactMenuItems } from "./contact-links";

/**
 * Row 11: the rendered WhatsApp link for a stored US number. BLNO stores
 * numbers like "(309) 555-0100"; before this the link was
 * `wa.me/3095550100`, which opens WhatsApp on nobody.
 */
describe("ContactLinks WhatsApp link", () => {
  it("prefixes a bare US number with +1 when no academy code is provided", () => {
    const html = renderToStaticMarkup(
      createElement(ContactLinks, { phone: "(555) 010-1234", name: "Ana" }),
    );
    expect(html).toContain('href="https://wa.me/15550101234"');
    // tel: keeps the number as typed.
    expect(html).toContain('href="tel:(555) 010-1234"');
  });

  it("uses the academy calling code from the admin shell's provider", () => {
    const html = renderToStaticMarkup(
      createElement(
        PhoneCountryProvider,
        { countryCode: "91" },
        createElement(ContactLinks, { phone: "98765 43210" }),
      ),
    );
    expect(html).toContain('href="https://wa.me/919876543210"');
  });

  it("falls back to +1 while the academy is still loading", () => {
    const html = renderToStaticMarkup(
      createElement(
        PhoneCountryProvider,
        { countryCode: undefined },
        createElement(ContactLinks, { phone: "555-010-1234" }),
      ),
    );
    expect(html).toContain('href="https://wa.me/15550101234"');
  });
});

describe("contactMenuItems", () => {
  it("builds the same WhatsApp destination for a row menu", () => {
    const item = contactMenuItems({ phone: "555-010-1234" }).find(
      (entry) => entry.key === "contact-whatsapp",
    );
    expect(item?.externalHref).toBe("https://wa.me/15550101234");
    const india = contactMenuItems({ phone: "98765 43210" }, "91").find(
      (entry) => entry.key === "contact-whatsapp",
    );
    expect(india?.externalHref).toBe("https://wa.me/919876543210");
  });
});
