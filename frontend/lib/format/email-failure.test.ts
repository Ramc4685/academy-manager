import { describe, expect, it } from "vitest";

import { emailFailureLabel } from "./email-failure";

describe("emailFailureLabel", () => {
  it("labels the public codes in plain words", () => {
    expect(emailFailureLabel("recipient_unsubscribed")).toBe(
      "They unsubscribed from these emails",
    );
    expect(emailFailureLabel("email_delivery_failed")).toBe("Delivery failed");
    expect(emailFailureLabel(null)).toBe("Delivery failed");
  });

  it("never shows raw snake_case for an unknown code", () => {
    expect(emailFailureLabel("parent_not_found")).toBe("Parent not found");
  });
});
