import { describe, expect, it } from "vitest";

import type { AdminClassPublicProfileView, AdminProgramView } from "@/lib/api/admin";
import {
  listableClasses,
  parseSeatsThreshold,
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
      theme: "floodlit",
      seats_left_threshold: 3,
    });
  });

  it("reads the saved theme and threshold, and repairs an unknown theme", () => {
    const view = {
      published: true,
      show_price: true,
      show_availability: true,
      price_period_default: "month" as const,
      trials_open: true,
      privacy_notice_url: null,
      theme: "daylight" as const,
      seats_left_threshold: 0,
      public_url: null,
    };
    expect(toPublicPageForm(view)).toMatchObject({ theme: "daylight", seats_left_threshold: 0 });
    expect(toPublicPageForm({ ...view, theme: "neon" as never }).theme).toBe("floodlit");
  });
});

describe("theme and seat threshold payload", () => {
  const original = toPublicPageForm(null);

  it("sends only the theme when only the theme changed", () => {
    expect(publicPagePayload(original, { ...original, theme: "showcase" })).toEqual({
      theme: "showcase",
    });
  });

  it("sends a threshold of 0: zero is a value, not 'unchanged'", () => {
    expect(publicPagePayload(original, { ...original, seats_left_threshold: 0 })).toEqual({
      seats_left_threshold: 0,
    });
  });
});

describe("parseSeatsThreshold", () => {
  it("clamps to 0 to 20 and treats blank or junk as 0", () => {
    expect(parseSeatsThreshold("5")).toBe(5);
    expect(parseSeatsThreshold("99")).toBe(20);
    expect(parseSeatsThreshold("-4")).toBe(0);
    expect(parseSeatsThreshold("")).toBe(0);
    expect(parseSeatsThreshold("abc")).toBe(0);
    expect(parseSeatsThreshold("2.6")).toBe(3);
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

  it("never carries the privacy link: it lives in Academy profile now", () => {
    const form = toPublicPageForm({
      published: true,
      show_price: true,
      show_availability: true,
      price_period_default: "month",
      trials_open: true,
      theme: "floodlit",
      seats_left_threshold: 3,
      privacy_notice_url: "https://riverside.example/privacy",
      public_url: null,
    });
    expect(form).not.toHaveProperty("privacy_notice_url");
    expect(publicPagePayload(form, { ...form, published: false })).toEqual({ published: false });
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
