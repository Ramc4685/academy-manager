import { describe, expect, it } from "vitest";

import type { CoachNarrative } from "@/lib/api/coach";

import { AI_STATUS_KEY, masteredOn, narrativeErrorCopy, narrativePanel } from "./progress-narrative";

const today = new Date(2026, 10, 4, 15, 30); // local
const key = "2026-11-04";
const iso = (d: Date) => d.toISOString();

describe("masteredOn", () => {
  it("is true only for a PASSED cell updated on that day", () => {
    expect(masteredOn({ a: { status: "PASSED", last_updated_at: iso(today) } }, key)).toBe(true);
    expect(masteredOn({ a: { status: "PRACTICING", last_updated_at: iso(today) } }, key)).toBe(false);
    const yesterday = new Date(2026, 10, 3, 15, 30);
    expect(masteredOn({ a: { status: "PASSED", last_updated_at: iso(yesterday) } }, key)).toBe(false);
    expect(masteredOn({ a: { status: "PASSED", last_updated_at: null } }, key)).toBe(false);
    expect(masteredOn({}, key)).toBe(false);
  });

  it("treats a naive timestamp as UTC, like the rest of the coach UI", () => {
    const naive = iso(today).replace(/Z$/, "");
    expect(masteredOn({ a: { status: "PASSED", last_updated_at: naive } }, key)).toBe(true);
  });
});

describe("narrativeErrorCopy", () => {
  it("maps each AI failure to its sentence", () => {
    expect(narrativeErrorCopy({ status: 503 })).toBe("AI notes are not enabled for this academy yet");
    expect(narrativeErrorCopy({ status: 403 })).toBe("AI notes are part of the Growth plan");
    expect(narrativeErrorCopy({ status: 429 })).toBe("This academy has used its AI drafts for the month");
    expect(narrativeErrorCopy({ status: 502 })).toBe("The note could not be read, try again");
    expect(narrativeErrorCopy({ status: 409 })).toBe("Nothing mastered that day to write about");
  });

  it("falls back to a plain sentence for anything else", () => {
    expect(narrativeErrorCopy({ status: 500 })).toBe("Couldn't draft the note. Try again.");
    expect(narrativeErrorCopy(new Error("offline"))).toBe("Couldn't draft the note. Try again.");
    expect(narrativeErrorCopy(null)).toBe("Couldn't draft the note. Try again.");
  });
});

it("queries B1's status under the shared admin key", () => {
  expect(AI_STATUS_KEY).toEqual(["admin", "ai", "status"]);
});

describe("narrativePanel", () => {
  const row = (status: CoachNarrative["status"], text = "Aarav flew."): CoachNarrative => ({
    narrative_id: `n-${status}`,
    student_id: "s1",
    for_date: "2026-11-04",
    kind: "evening_wins",
    text,
    status,
    approver: null,
  });

  it("waits for the read, then offers Draft when the day has no row", () => {
    expect(narrativePanel(null, undefined)).toEqual({ panel: "loading", row: null });
    expect(narrativePanel(null, null)).toEqual({ panel: "draft", row: null });
  });

  it("shows a persisted draft for review after a refresh, and decided rows by status", () => {
    expect(narrativePanel(null, row("pending_review")).panel).toBe("review");
    expect(narrativePanel(null, row("approved")).panel).toBe("approved");
    expect(narrativePanel(null, row("rejected")).panel).toBe("rejected");
  });

  it("prefers the row from this session's draft or decision over the loaded one", () => {
    const fresh = row("pending_review", "Drafted again.");
    expect(narrativePanel(fresh, row("rejected"))).toEqual({ panel: "review", row: fresh });
    expect(narrativePanel(row("approved"), undefined).panel).toBe("approved");
  });
});
