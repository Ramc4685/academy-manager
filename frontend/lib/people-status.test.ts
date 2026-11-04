import { describe, expect, it } from "vitest";

import {
  CARD_LABELS,
  LOGIN_LABELS,
  cardChip,
  cardStateFromRegistration,
  describeCardDeclineCode,
  loginChip,
  loginStateFromRegistration,
  userLoginChip,
} from "./people-status";

describe("one vocabulary for Login and Card (#840)", () => {
  it("names the login fact the same way everywhere", () => {
    expect(loginChip("not_invited").label).toBe("Not invited");
    expect(loginChip("invited").label).toBe("Invited");
    expect(loginChip("active").label).toBe("Active");
    expect(LOGIN_LABELS.active).toBe("Active");
  });

  it("names the card fact the same way everywhere", () => {
    expect(cardChip("no_card").label).toBe("No card");
    expect(cardChip("on_file").label).toBe("Card on file");
    expect(cardChip("declined").label).toBe("Card declined");
    expect(CARD_LABELS.on_file).toBe("Card on file");
  });

  it("uses sentence case, never the SHOUTED billing-chip wording", () => {
    for (const label of [...Object.values(LOGIN_LABELS), ...Object.values(CARD_LABELS)]) {
      expect(label).not.toBe(label.toUpperCase());
    }
  });
});

describe("the two People enums agree on the card fact", () => {
  it("maps the families list and the family detail onto the same card state", () => {
    // Billing-setup spelling (list) vs family-billing spelling (detail).
    expect(cardStateFromRegistration("card_on_file")).toBe(
      cardStateFromRegistration("registered"),
    );
    expect(cardStateFromRegistration("account_no_card")).toBe(
      cardStateFromRegistration("invited"),
    );
    expect(cardStateFromRegistration("no_account")).toBe(
      cardStateFromRegistration("not_invited"),
    );
    expect(cardStateFromRegistration("card_on_file")).toBe("on_file");
    expect(cardStateFromRegistration("no_account")).toBe("no_card");
  });

  it("maps each enum onto the login fact its backend actually knows", () => {
    // Billing setup knows whether a login account exists.
    expect(loginStateFromRegistration("no_account")).toBe("not_invited");
    expect(loginStateFromRegistration("account_no_card")).toBe("active");
    expect(loginStateFromRegistration("card_on_file")).toBe("active");
    // Family billing knows whether an invite went out.
    expect(loginStateFromRegistration("not_invited")).toBe("not_invited");
    expect(loginStateFromRegistration("invited")).toBe("invited");
    expect(loginStateFromRegistration("registered")).toBe("active");
  });
});

describe("describeCardDeclineCode", () => {
  it("never leaks a raw Stripe code", () => {
    for (const code of [
      "card_declined",
      "insufficient_funds",
      "expired_card",
      "incorrect_cvc",
      "processing_error",
      "generic_decline",
      "authentication_required",
      "some_future_code_we_have_never_seen",
    ]) {
      const sentence = describeCardDeclineCode(code);
      expect(sentence).not.toContain(code);
      expect(sentence).not.toMatch(/_/);
      expect(sentence.endsWith(".")).toBe(true);
    }
  });

  it("explains the common declines in plain words", () => {
    expect(describeCardDeclineCode("card_declined")).toMatch(/declin/i);
    expect(describeCardDeclineCode("insufficient_funds")).toMatch(/funds/i);
    expect(describeCardDeclineCode("expired_card")).toMatch(/expired/i);
  });

  it("still says something useful when there is no code", () => {
    expect(describeCardDeclineCode(null)).toMatch(/fail/i);
    expect(describeCardDeclineCode(undefined)).toMatch(/fail/i);
    expect(describeCardDeclineCode("")).toMatch(/fail/i);
  });
});

describe("userLoginChip", () => {
  it("says Active, not ACTIVE, for an account that can log in", () => {
    expect(userLoginChip("active")).toEqual({ label: "Active", variant: "enrolled" });
  });

  it("uses the shared words for the other known account states", () => {
    expect(userLoginChip("invited").label).toBe("Invited");
    expect(userLoginChip("inactive").label).toBe("No access");
    expect(userLoginChip("disabled").label).toBe("No access");
  });

  it("falls back to a neutral chip rather than inventing a claim", () => {
    expect(userLoginChip("archived")).toEqual({ label: "Archived", variant: "manual" });
    expect(userLoginChip("")).toEqual({ label: "Unknown", variant: "manual" });
  });
});
