import { describe, expect, it } from "vitest";

import type { AdminClassPublicProfileView, AdminProgramView } from "@/lib/api/admin";
import {
  listableClasses,
  privacyUrlError,
  programOptions,
  publicPagePayload,
  toPublicPageForm,
  viewPageHref,
} from "@/lib/public-page/admin-settings";

describe("toPublicPageForm", () => {
  it("falls back to the domain defaults before the settings load", () => {
    expect(toPublicPageForm(null)).toEqual({
      published: false,
      show_price: true,
      show_availability: true,
      price_period_default: "month",
      trials_open: true,
      privacy_notice_url: "",
    });
  });
});

describe("publicPagePayload", () => {
  const original = toPublicPageForm(null);

  it("is empty when nothing changed", () => {
    expect(publicPagePayload(original, { ...original })).toEqual({});
  });

  it("sends only the keys that changed", () => {
    expect(publicPagePayload(original, { ...original, published: true })).toEqual({
      published: true,
    });
    expect(
      publicPagePayload(original, {
        ...original,
        show_price: false,
        price_period_default: "term",
      })
    ).toEqual({ show_price: false, price_period_default: "term" });
  });

  it("trims the privacy link and sends a cleared link as null", () => {
    const withLink = { ...original, privacy_notice_url: "https://riverside.example/privacy" };
    expect(
      publicPagePayload(original, { ...original, privacy_notice_url: "  https://a.example/p " })
    ).toEqual({ privacy_notice_url: "https://a.example/p" });
    expect(publicPagePayload(withLink, { ...withLink, privacy_notice_url: "  " })).toEqual({
      privacy_notice_url: null,
    });
    expect(
      publicPagePayload(withLink, { ...withLink, privacy_notice_url: " https://riverside.example/privacy" })
    ).toEqual({});
  });
});

describe("privacyUrlError", () => {
  it.each(["", "  ", "https://riverside.example/privacy", "http://riverside.example"])(
    "accepts %j",
    (value) => expect(privacyUrlError(value)).toBeNull()
  );

  it.each([
    "javascript:alert(1)",
    "data:text/html,hi",
    "ftp://riverside.example/p",
    "riverside.example/privacy",
    "mailto:owner@riverside.example",
  ])("rejects %j", (value) => expect(privacyUrlError(value)).not.toBeNull());
});

describe("viewPageHref", () => {
  it("prefers the academy's own domain from the server", () => {
    expect(
      viewPageHref("https://riverside.example/", {
        origin: "https://academy.courtmastr.com",
        host: "academy.courtmastr.com",
      })
    ).toBe("https://riverside.example/");
  });

  it("uses the current tenant host when the server has no domain on record", () => {
    expect(
      viewPageHref(null, { origin: "https://riverside.example", host: "riverside.example" })
    ).toBe("https://riverside.example/");
  });

  it("never points at the product host's landing page", () => {
    expect(
      viewPageHref(null, {
        origin: "https://academy.courtmastr.com",
        host: "academy.courtmastr.com",
      })
    ).toBeNull();
    expect(viewPageHref(null, null)).toBeNull();
  });
});

describe("listableClasses", () => {
  const row = (over: Partial<AdminClassPublicProfileView>): AdminClassPublicProfileView => ({
    session_id: "s",
    title: null,
    status: "scheduled",
    program_id: null,
    published: false,
    price_period: null,
    coach_display: "full_name",
    public_description: null,
    level: null,
    age_band: null,
    ...over,
  });

  it("hides ended classes unless they are still switched on, sorted by title", () => {
    const out = listableClasses([
      row({ session_id: "s-3", title: "juniors" }),
      row({ session_id: "s-1", title: "Adults", status: "completed" }),
      row({ session_id: "s-2", title: "Beginners", status: "cancelled", published: true }),
      row({ session_id: "s-4", title: "Advanced", status: null }),
    ]);
    expect(out.map((r) => r.session_id)).toEqual(["s-4", "s-2", "s-3"]);
  });
});

describe("programOptions", () => {
  const program = (id: string, name: string, archived = false): AdminProgramView => ({
    program_id: id,
    name,
    public_description: null,
    level: null,
    age_band: null,
    sort_order: 0,
    archived,
    created_at: "2026-09-23T12:00:00Z",
    updated_at: "2026-09-23T12:00:00Z",
  });
  const programs = [program("p-juniors", "Juniors"), program("p-old", "Winter Squad", true)];

  it("offers only active programs to an unassigned class", () => {
    expect(programOptions(programs, null)).toEqual([{ value: "p-juniors", label: "Juniors" }]);
  });

  it("keeps a class's archived program visible and marked", () => {
    expect(programOptions(programs, "p-old")).toEqual([
      { value: "p-juniors", label: "Juniors" },
      { value: "p-old", label: "Winter Squad (archived)" },
    ]);
  });

  it("never shows an unlisted program id as unassigned", () => {
    expect(programOptions(programs, "p-gone")).toEqual([
      { value: "p-juniors", label: "Juniors" },
      { value: "p-gone", label: "Unknown program" },
    ]);
  });

  it("does not duplicate an active current program", () => {
    expect(programOptions(programs, "p-juniors")).toHaveLength(1);
  });
});
