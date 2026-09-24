import { describe, expect, it } from "vitest";

import { SENDER_NAME_MAX_LENGTH, senderNameError } from "./branding-panel";

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
