import { describe, expect, it } from "vitest";

import type { FamilyMessage } from "@/lib/api/admin-family-crm";

import {
  MAX_CONTACT_LOG_NOTE_LEN,
  channelLabel,
  contactNoteError,
  handoffHref,
  smsHref,
  sourceLabel,
  statusLabel,
  statusVariant,
  unconfirmedCount,
  warningText,
} from "./family-messages";

function msg(id: string, over: Partial<FamilyMessage> = {}): FamilyMessage {
  return {
    entry_id: id,
    at: "2026-09-20T10:00:00Z",
    channel: "email",
    source: "campaign",
    status: "sent",
    summary: "Email: Term dates",
    detail: null,
    recipient: "parent@example.test",
    author_user_id: null,
    failed_reason: null,
    log_id: null,
    can_complete: false,
    ...over,
  };
}

describe("family messages labels", () => {
  it("names every channel, source and status in plain words", () => {
    expect(channelLabel("whatsapp")).toBe("WhatsApp");
    expect(channelLabel("in_person")).toBe("In person");
    expect(sourceLabel("invoice_copy")).toBe("Invoice copy");
    expect(sourceLabel("staff_log")).toBe("Logged by staff");
    expect(statusLabel("not_logged")).toBe("Not confirmed");
    expect(statusVariant("failed")).toBe("failed");
    expect(statusVariant("queued")).toBe("pending");
  });
});

describe("handoff links", () => {
  const contact = { phone: "+1 (555) 010-1234", email: " family@example.test " };

  it("builds digits-only wa.me and sms links and a trimmed mailto", () => {
    expect(handoffHref("whatsapp", contact)).toBe("https://wa.me/15550101234");
    expect(handoffHref("sms", contact)).toBe("sms:+15550101234");
    expect(handoffHref("email", contact)).toBe("mailto:family@example.test");
  });

  it("gives no link when the family has no number or email", () => {
    expect(handoffHref("whatsapp", { phone: null })).toBeUndefined();
    expect(handoffHref("sms", { phone: "  " })).toBeUndefined();
    expect(handoffHref("email", { email: "" })).toBeUndefined();
    expect(smsHref("555 0101")).toBe("sms:5550101");
  });
});

describe("contact note", () => {
  it("accepts an empty or short note and refuses one over the cap", () => {
    expect(contactNoteError("")).toBeNull();
    expect(contactNoteError("Called about Saturday")).toBeNull();
    expect(contactNoteError("x".repeat(MAX_CONTACT_LOG_NOTE_LEN + 1))).toMatch(/at most/);
  });
});

describe("warnings and counts", () => {
  it("names unavailable sources and counts unconfirmed handoffs", () => {
    expect(warningText([])).toBeNull();
    expect(warningText(["digest_unavailable", "odd_unavailable"])).toContain(
      "parent digests, odd",
    );
    expect(
      unconfirmedCount([
        msg("a"),
        msg("b", { source: "staff_log", status: "not_logged", channel: "sms" }),
      ]),
    ).toBe(1);
  });
});
