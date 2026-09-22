import { describe, expect, it } from "vitest";

import {
  healthPillTone,
  invoiceStatusLabel,
  truncationLine,
  webhookEventLabel,
} from "./billing-health";

describe("healthPillTone", () => {
  it("maps the three verdict states", () => {
    expect(healthPillTone("blocked").tone).toBe("red");
    expect(healthPillTone("attention").tone).toBe("amber");
    expect(healthPillTone("ok").tone).toBe("green");
  });

  it("never calls an unknown state healthy", () => {
    // The bug this page was rebuilt to remove was a green pill above a red
    // card; an unreadable state must not resurrect it.
    expect(healthPillTone("something-new").tone).toBe("amber");
    expect(healthPillTone(undefined).tone).toBe("amber");
    expect(healthPillTone(null).tone).toBe("amber");
    expect(healthPillTone("").tone).toBe("amber");
  });
});

describe("truncationLine", () => {
  it("says nothing when the list holds everything", () => {
    expect(truncationLine(3, 3)).toBeNull();
    expect(truncationLine(50, 0)).toBeNull();
  });

  it("names both numbers when the capped list hides some", () => {
    expect(truncationLine(50, 214)).toBe(
      "Showing the 50 most recent of 214 quarantined events.",
    );
  });
});

describe("webhookEventLabel", () => {
  it("says what the Stripe event was, not its key", () => {
    expect(webhookEventLabel("invoice.payment_failed")).toBe("Invoice payment failed");
    expect(webhookEventLabel("payment_intent.succeeded")).toBe("Payment succeeded");
    expect(webhookEventLabel("checkout.session.completed")).toBe("Checkout completed");
  });

  it("humanises an event type it has never seen rather than printing the key", () => {
    // The backend can forward a new Stripe event without the UI shipping again;
    // what it must never do is put a dotted snake_case key on the screen.
    const label = webhookEventLabel("invoice.finalization_failed");
    expect(label).toBe("Invoice finalization failed");
    expect(label).not.toContain("_");
    expect(label).not.toContain(".");
  });

  it("has wording for a missing type", () => {
    expect(webhookEventLabel(null)).toBe("Unknown event");
    expect(webhookEventLabel("")).toBe("Unknown event");
  });
});

describe("invoiceStatusLabel", () => {
  it("reads as a sentence fragment, never the stored key", () => {
    expect(invoiceStatusLabel("paid")).toBe("paid");
    expect(invoiceStatusLabel("past_due")).toBe("past due");
    expect(invoiceStatusLabel("partially_paid")).toBe("partly paid");
  });

  it("never leaks an underscore for a status it does not know", () => {
    expect(invoiceStatusLabel("needs_review")).toBe("needs review");
  });

  it("falls back to a neutral word when the backend sends nothing", () => {
    expect(invoiceStatusLabel(null)).toBe("updated");
    expect(invoiceStatusLabel(undefined)).toBe("updated");
  });
});
