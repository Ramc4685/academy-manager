import { describe, expect, it } from "vitest";

import { mailtoHref, telHref, whatsappHref } from "./contact-links";

/**
 * Issue #865: an admin working a phone list is usually about to call, message
 * or email the person in front of them. Every surface that printed a phone
 * number as plain text made that a copy-paste job.
 *
 * The three hrefs are derived ONCE here so no surface invents its own: a
 * `wa.me` link built from a formatted number ("+1 (555) 010-1234") is a dead
 * link, and a `tel:` on an empty string is a link to nowhere.
 */

describe("telHref", () => {
  it("passes the number through unmodified, as the student header already does", () => {
    // `tel:` accepts the visual-separator characters, and keeping the raw
    // string means the link text and the href never disagree.
    expect(telHref("+1 (555) 010-1234")).toBe("tel:+1 (555) 010-1234");
  });

  it("is undefined when there is no number, so no dead link renders", () => {
    expect(telHref(undefined)).toBeUndefined();
    expect(telHref(null)).toBeUndefined();
    expect(telHref("")).toBeUndefined();
    expect(telHref("   ")).toBeUndefined();
  });
});

describe("whatsappHref", () => {
  /**
   * Row 11: the same rules as the backend's `normalize_wa_number`
   * (`backend/v2/shared/comms/whatsapp.py`). wa.me needs the full
   * international number; a bare US number used to become `wa.me/5550101234`,
   * which opens WhatsApp on nobody.
   */
  it("prefixes a bare 10-digit national number with the academy calling code", () => {
    expect(whatsappHref("(555) 010-1234")).toBe("https://wa.me/15550101234");
    expect(whatsappHref("555.010.1234", "1")).toBe("https://wa.me/15550101234");
    expect(whatsappHref("98765 43210", "91")).toBe("https://wa.me/919876543210");
  });

  it("keeps a number that already carries the calling code", () => {
    expect(whatsappHref("+1 (555) 010-1234")).toBe("https://wa.me/15550101234");
    expect(whatsappHref("1-555-010-1234")).toBe("https://wa.me/15550101234");
  });

  it("trusts an explicit + or 00 international prefix over the default", () => {
    expect(whatsappHref("+91 98765 43210")).toBe("https://wa.me/919876543210");
    expect(whatsappHref("0044 7911 123456")).toBe("https://wa.me/447911123456");
    expect(whatsappHref("+44 7911 123456", "1")).toBe("https://wa.me/447911123456");
  });

  it("refuses to guess rather than link to a stranger", () => {
    // A leading trunk 0 means the number is not from the default country.
    expect(whatsappHref("07911 123456")).toBeUndefined();
    // Too short, or a length that cannot be attributed to a country code.
    expect(whatsappHref("555-0100")).toBeUndefined();
    expect(whatsappHref("919876543210")).toBeUndefined();
    expect(whatsappHref("+12 34")).toBeUndefined();
  });

  it("is undefined when nothing dialable is left", () => {
    expect(whatsappHref(null)).toBeUndefined();
    expect(whatsappHref("")).toBeUndefined();
    expect(whatsappHref("ext.")).toBeUndefined();
  });
});

describe("mailtoHref", () => {
  it("builds a mailto for a real address", () => {
    expect(mailtoHref(" amit@example.com ")).toBe("mailto:amit@example.com");
  });

  it("is undefined when there is no address", () => {
    expect(mailtoHref(undefined)).toBeUndefined();
    expect(mailtoHref("")).toBeUndefined();
  });
});
