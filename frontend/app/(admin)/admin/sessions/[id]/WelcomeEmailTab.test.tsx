import { createElement } from "react";
import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it } from "vitest";

import type { AdminAcademyView, AdminSessionView } from "@/lib/api/admin";

import { WelcomeEmailRows } from "./WelcomeEmailTab";
import { buildPackPatch, packDefaults, resolveRow, PACK_ROWS } from "./welcome-email-model";

function session(overrides: Partial<AdminSessionView> = {}): AdminSessionView {
  return {
    session_id: "sess-1",
    coach_id: "coach-1",
    coach_name: "Coach",
    assistant_coach_ids: [],
    assistant_coach_names: [],
    title: "Wednesday",
    location: "Court 1",
    start_at: "2026-09-30T22:45:00Z",
    end_at: "2026-09-30T23:30:00Z",
    days_of_week: ["Wed"],
    start_time: "17:45",
    end_time: "18:30",
    timezone: "America/Chicago",
    capacity: 12,
    status: "scheduled",
    enrolled_count: 0,
    waitlist_count: 0,
    ...overrides,
  } as AdminSessionView;
}

const ACADEMY = {
  default_venue_address: "123 Court St",
  default_parking_note: null,
  default_what_to_bring: "Water bottle",
  default_arrival_minutes_before: 10,
  default_coach_contact_policy: "Message on WhatsApp only",
} as AdminAcademyView;

const DEFAULTS = packDefaults(ACADEMY, "Academy absence policy");

function html(s: AdminSessionView, drafts = {}, editing = new Set<never>()): string {
  return renderToStaticMarkup(
    createElement(WelcomeEmailRows, {
      session: s,
      defaults: DEFAULTS,
      drafts,
      editing,
      onDraft: () => undefined,
      onOverride: () => undefined,
      onCancelEdit: () => undefined,
      onReset: () => undefined,
    }),
  );
}

function row(markup: string, field: string): string {
  const rows = markup.split(/(?=<div data-testid="welcome-row-[a-z_]+" data-state)/);
  return rows.find((chunk) => chunk.startsWith(`<div data-testid="welcome-row-${field}"`)) ?? "";
}

describe("Welcome email rows", () => {
  it("shows the class's own value with a This class tag and Reset", () => {
    const markup = html(session({ venue_address: "Class hall" }));
    const venue = row(markup, "venue_address");
    expect(venue).toContain("Class hall");
    expect(venue).toContain("This class");
    expect(venue).toContain("Reset Venue address");
    expect(venue).not.toContain("(academy default)");
    expect(venue).not.toContain("123 Court St");
  });

  it("shows the academy default in grey with Override when the class is blank", () => {
    const venue = row(html(session()), "venue_address");
    expect(venue).toContain("123 Court St");
    expect(venue).toContain("(academy default)");
    expect(venue).toContain("text-rally-muted");
    expect(venue).toContain("Override Venue address");
    expect(venue).not.toContain("Reset");
  });

  it("falls back to Family policies for absences and Settings for coach contact", () => {
    const markup = html(session());
    expect(row(markup, "absence_policy")).toContain("Academy absence policy");
    expect(row(markup, "coach_contact_policy")).toContain("Message on WhatsApp only");
  });

  it("reads Not set when neither the class nor the academy has a value", () => {
    const markup = html(session());
    // Parking has no academy default in this fixture; WhatsApp never has one.
    expect(row(markup, "parking_notes")).toContain("Not set");
    expect(row(markup, "whatsapp_group_link")).toContain("Not set");
    expect(row(markup, "whatsapp_group_link")).toContain("Set Group chat");
  });

  it("never renders 0 minutes: an arrival of 0 or null is Not set", () => {
    const noDefault = packDefaults({ ...ACADEMY, default_arrival_minutes_before: 0 }, "");
    for (const arrival of [0, null]) {
      const markup = renderToStaticMarkup(
        createElement(WelcomeEmailRows, {
          session: session({ arrival_minutes_before: arrival }),
          defaults: noDefault,
          drafts: {},
          editing: new Set(),
          onDraft: () => undefined,
          onOverride: () => undefined,
          onCancelEdit: () => undefined,
          onReset: () => undefined,
        }),
      );
      expect(row(markup, "arrival_minutes_before")).toContain("Not set");
      expect(markup).not.toContain("0 minutes");
    }
  });

  it("shows the academy arrival default as minutes, and the class value over it", () => {
    expect(row(html(session()), "arrival_minutes_before")).toContain("10 minutes before start");
    const own = row(html(session({ arrival_minutes_before: 1 })), "arrival_minutes_before");
    expect(own).toContain("1 minute before start");
    expect(own).toContain("This class");
  });

  it("a staged reset shows the default again before Save", () => {
    const markup = html(session({ venue_address: "Class hall" }), { venue_address: "" });
    const venue = row(markup, "venue_address");
    expect(venue).toContain("123 Court St");
    expect(venue).toContain("(academy default)");
  });

  it("renders an input for a row being edited", () => {
    const markup = html(session(), { venue_address: "123 Court St" }, new Set(["venue_address"]) as never);
    expect(markup).toContain('data-testid="welcome-input-venue_address"');
  });
});

describe("buildPackPatch", () => {
  it("sends nothing when nothing changed", () => {
    expect(buildPackPatch(session({ venue_address: "Hall" }), { venue_address: "Hall " })).toEqual({});
  });

  it("sends only the changed pack fields, never schedule, coach, seats or price", () => {
    const s = session({ venue_address: "Hall", parking_notes: "Lot A", amount_cents: 6000 });
    const patch = buildPackPatch(s, {
      venue_address: "New hall",
      what_to_bring: " Racquet ",
      arrival_minutes_before: "15",
    });
    expect(patch).toEqual({
      venue_address: "New hall",
      what_to_bring: "Racquet",
      arrival_minutes_before: 15,
    });
    const packKeys = new Set(PACK_ROWS.map((spec) => spec.field));
    for (const key of Object.keys(patch)) expect(packKeys.has(key as never)).toBe(true);
    for (const forbidden of ["title", "location", "capacity", "amount_cents", "days_of_week", "coach_id"]) {
      expect(patch).not.toHaveProperty(forbidden);
    }
  });

  it("clears a field with an explicit null (Reset)", () => {
    expect(buildPackPatch(session({ venue_address: "Hall", arrival_minutes_before: 5 }), {
      venue_address: "",
      arrival_minutes_before: "",
    })).toEqual({ venue_address: null, arrival_minutes_before: null });
  });
});

describe("resolveRow", () => {
  const venue = PACK_ROWS.find((spec) => spec.field === "venue_address")!;
  const whatsapp = PACK_ROWS.find((spec) => spec.field === "whatsapp_group_link")!;

  it("prefers the class's own value", () => {
    expect(resolveRow(venue, "Hall", DEFAULTS)).toEqual({ kind: "own", text: "Hall" });
  });
  it("uses the default when blank", () => {
    expect(resolveRow(venue, "  ", DEFAULTS)).toEqual({ kind: "default", text: "123 Court St" });
  });
  it("never defaults the WhatsApp link", () => {
    expect(resolveRow(whatsapp, "", { whatsapp_group_link: "https://x" })).toEqual({ kind: "unset" });
  });
});
