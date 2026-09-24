import { describe, expect, it } from "vitest";

import type { FamilyContact } from "@/lib/api/admin-family-contacts";

import {
  CONTACT_SWITCHES,
  apiFieldError,
  contactDraftErrors,
  contactPatch,
  contactPayload,
  detailsDraftErrors,
  detailsDraftFrom,
  detailsPatch,
  draftFromContact,
  emptyContactDraft,
  isContactDraftDirty,
  isDetailsDirty,
  parseTags,
} from "./family-contacts";

const CONTACT: FamilyContact = {
  contact_id: "c-1",
  parent_id: "parent-1",
  name: "Second Testparent",
  relationship: "parent",
  email: "second@example.test",
  phone: null,
  gets_notices: false,
  gets_invoices: false,
  created_by: "u-1",
  created_at: "2026-09-23T15:00:00Z",
  updated_at: "2026-09-23T15:00:00Z",
};

describe("contact drafts", () => {
  it("starts with both switches off", () => {
    const draft = emptyContactDraft();
    expect(draft.gets_notices).toBe(false);
    expect(draft.gets_invoices).toBe(false);
  });

  it("labels the switches and says the payment link stays with the primary parent", () => {
    expect(CONTACT_SWITCHES.map((s) => s.label)).toEqual([
      "Gets notices",
      "Gets invoices (opted in)",
    ]);
    expect(CONTACT_SWITCHES[1].description).toMatch(/Invoice emails to this family also go to this email/);
    expect(CONTACT_SWITCHES[1].description).toMatch(/payment link stays with the primary parent/);
    expect(CONTACT_SWITCHES[1].description).not.toMatch(/once invoice email wiring ships/);
  });

  it("reports field errors like the backend", () => {
    expect(contactDraftErrors({ ...emptyContactDraft() }).name).toBeTruthy();
    expect(contactDraftErrors({ ...emptyContactDraft(), name: "X" }).email).toMatch(
      /email or a phone/,
    );
    expect(contactDraftErrors({ ...emptyContactDraft(), name: "X", email: "nope" }).email).toMatch(
      /valid email/,
    );
    expect(contactDraftErrors({ ...emptyContactDraft(), name: "X", phone: "12" }).phone).toMatch(
      /valid phone/,
    );
    expect(
      contactDraftErrors({
        ...emptyContactDraft(),
        name: "X",
        phone: "555-010-0001",
        gets_notices: true,
      }).gets_notices,
    ).toMatch(/Add an email/);
    expect(
      contactDraftErrors({
        ...emptyContactDraft(),
        name: "X",
        email: "x@example.test",
      }),
    ).toEqual({});
  });

  it("sends blanks as null and patches only what changed", () => {
    expect(
      contactPayload({
        ...emptyContactDraft(),
        name: " X ",
        email: " ",
        phone: "555-010-0001",
      }),
    ).toMatchObject({ name: "X", email: null, phone: "555-010-0001" });
    const draft = draftFromContact(CONTACT);
    expect(isContactDraftDirty(draft, draftFromContact(CONTACT))).toBe(false);
    expect(contactPatch(CONTACT, draft)).toEqual({});
    expect(contactPatch(CONTACT, { ...draft, gets_notices: true, email: "" })).toEqual({
      gets_notices: true,
      email: null,
    });
  });
});

describe("family details drafts", () => {
  it("round-trips and patches only changed fields", () => {
    const saved = detailsDraftFrom({
      family_id: "parent-1",
      address: "1 Test Street",
      preferred_channel: "sms",
      heard_about_us: null,
      tags: ["VIP", "Sibling"],
      updated_by: null,
      updated_at: null,
    });
    expect(saved.tags).toBe("VIP, Sibling");
    expect(isDetailsDirty(saved, saved)).toBe(false);
    expect(isDetailsDirty({ ...saved, tags: "VIP,Sibling " }, saved)).toBe(false);
    const edited = {
      ...saved,
      address: "",
      preferred_channel: "" as const,
      tags: "vip, New",
    };
    expect(detailsPatch(saved, edited)).toEqual({
      address: null,
      preferred_channel: null,
      tags: ["vip", "New"],
    });
    expect(detailsDraftFrom(null)).toEqual({
      address: "",
      preferred_channel: "",
      heard_about_us: "",
      tags: "",
    });
  });

  it("parses tags and checks caps", () => {
    expect(parseTags(" VIP , vip,,  Sibling  ")).toEqual(["VIP", "Sibling"]);
    const draft = detailsDraftFrom(null);
    expect(detailsDraftErrors({ ...draft, address: "a".repeat(301) }).address).toBeTruthy();
    expect(detailsDraftErrors({ ...draft, tags: "a".repeat(41) }).tags).toBeTruthy();
    expect(
      detailsDraftErrors({
        ...draft,
        tags: Array.from({ length: 21 }, (_, i) => `t${i}`).join(),
      }).tags,
    ).toMatch(/at most 20/);
  });
});

describe("apiFieldError", () => {
  it("reads the backend's field", () => {
    expect(apiFieldError({ message: "Bad", details: { field: "email" } })).toEqual({
      field: "email",
      message: "Bad",
    });
    expect(apiFieldError(null).field).toBeNull();
  });
});
