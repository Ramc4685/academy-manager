import { describe, expect, it } from "vitest";

import { almostThereDraft, composeHref, stuckDraft, weeksAgo } from "./pathway-drafts";

const NOW = Date.parse("2026-11-02T12:00:00Z");
const WEEK = 7 * 24 * 60 * 60 * 1000;
const LEVELS = [
  { level_id: "l1", name: "Grip & Control", sequence: 1, player_count: 3, requires_admin_approval: false },
  { level_id: "l2", name: "Net & Movement", sequence: 2, player_count: 2, requires_admin_approval: false },
];

describe("almostThereDraft", () => {
  const row = {
    student_id: "st-a",
    student_name: "Aarav Shah",
    level_name: "Grip & Control",
    level_sequence: 1,
    missing_skill_name: "Basic rally",
  };

  it("names the child, the one skill left, and the next level", () => {
    const draft = almostThereDraft(row, LEVELS);
    expect(draft).toContain("Quick update on Aarav:");
    expect(draft).not.toContain("Shah");
    expect(draft).toContain("finish Level 1 (Grip & Control), and it's Basic rally.");
    expect(draft).toContain("moves up to Level 2 (Net & Movement).");
    expect(draft).not.toContain("\n");
  });

  it("says the pathway is finished when there is no next level", () => {
    const draft = almostThereDraft({ ...row, level_sequence: 2, level_name: "Net & Movement" }, LEVELS);
    expect(draft).toContain("has finished the whole pathway.");
  });
});

describe("stuckDraft", () => {
  const row = {
    student_id: "st-e",
    student_name: "Ethan",
    level_name: "Net & Movement",
    level_sequence: 2,
    skills_passed: 2,
    skills_total: 6,
    last_win_at: new Date(NOW - 7 * WEEK).toISOString(),
    level_started_at: new Date(NOW - 12 * WEEK).toISOString(),
  };

  it("offers a 1-on-1 with skills passed and time since the last win", () => {
    const draft = stuckDraft(row, NOW);
    expect(draft).toContain("Ethan has passed 2 of 6 skills in Level 2 (Net & Movement)");
    expect(draft).toContain("the last new skill was 7 weeks ago.");
    expect(draft).toContain("offer Ethan a 1-on-1 session");
  });

  it("counts from placement when the child has no win yet", () => {
    const draft = stuckDraft({ ...row, skills_passed: 0, last_win_at: null }, NOW);
    expect(draft).toContain("starting this level 12 weeks ago.");
  });
});

describe("weeksAgo", () => {
  it("rounds a week or less to 'a week ago'", () => {
    expect(weeksAgo(new Date(NOW - WEEK).toISOString(), NOW)).toBe("a week ago");
    expect(weeksAgo(new Date(NOW - 3 * WEEK).toISOString(), NOW)).toBe("3 weeks ago");
  });
});

describe("composeHref", () => {
  it("opens the DM composer for the parent with the draft encoded", () => {
    const href = composeHref("par 1", "Hi & bye?");
    const url = new URL(href, "https://x.test");
    expect(url.pathname).toBe("/admin/messages");
    expect(url.searchParams.get("dm")).toBe("par 1");
    expect(url.searchParams.get("draft")).toBe("Hi & bye?");
  });
});
