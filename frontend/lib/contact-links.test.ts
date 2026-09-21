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
  it("strips every non-digit, because wa.me only accepts digits", () => {
    expect(whatsappHref("+1 (555) 010-1234")).toBe("https://wa.me/15550101234");
  });

  it("keeps a plain international number as-is", () => {
    expect(whatsappHref("919876543210")).toBe("https://wa.me/919876543210");
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
