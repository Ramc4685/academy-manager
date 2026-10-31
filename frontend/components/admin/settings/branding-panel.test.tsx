import { describe, expect, it } from "vitest";

import { SENDER_NAME_MAX_LENGTH, brandColorError, senderNameError } from "./branding-panel";

describe("senderNameError (L9a)", () => {
  it("accepts ordinary and unicode names", () => {
    expect(senderNameError("Alpha Shuttle Club")).toBeNull();
    expect(senderNameError("Club Élan 羽毛球")).toBeNull();
    expect(senderNameError("")).toBeNull();
  });

  it("rejects header injection and angle brackets", () => {
    expect(senderNameError("Alpha\r\nBcc: x@example.com")).toMatch(/line breaks/);
    expect(senderNameError("Alpha\nX")).toMatch(/line breaks/);
    expect(senderNameError("Alpha <spoof@example.com>")).toMatch(/angle brackets/);
  });

  it("caps the trimmed length", () => {
    expect(senderNameError("x".repeat(SENDER_NAME_MAX_LENGTH))).toBeNull();
    expect(senderNameError("x".repeat(SENDER_NAME_MAX_LENGTH + 1))).toMatch(/80 characters/);
  });
});

describe("brandColorError (Settings overhaul Phase 3 PR 9)", () => {
  it("accepts blank (unset) and valid 3/6-digit hex", () => {
    expect(brandColorError("")).toBeNull();
    expect(brandColorError("   ")).toBeNull();
    expect(brandColorError("#2563eb")).toBeNull();
    expect(brandColorError("#fff")).toBeNull();
  });

  it("rejects anything that is not a hex colour", () => {
    expect(brandColorError("not-a-color")).toMatch(/hex value/);
    expect(brandColorError("2563eb")).toMatch(/hex value/);
    expect(brandColorError("#12")).toMatch(/hex value/);
    expect(brandColorError("#1234567")).toMatch(/hex value/);
  });
});
