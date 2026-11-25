import { createElement } from "react";
import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it } from "vitest";

import type { ParentProgressJourney } from "@/lib/api/parent";

import {
  LevelRing,
  LevelStrip,
  MilestoneList,
  RecentWins,
  SkillChecklist,
  formatWinDate,
  milestoneLabel,
} from "./journey";

type Current = NonNullable<ParentProgressJourney["current_level"]>;

function current(overrides: Partial<Current> = {}): Current {
  return {
    level_id: "l2",
    name: "Net & Movement",
    number: 2,
    skills_done: 3,
    skills_total: 6,
    skills_remaining: 3,
    has_next_level: true,
    pace_weeks: 5,
    ...overrides,
  };
}

const text = (markup: string) => markup.replace(/<[^>]+>/g, " ").replace(/\s+/g, " ");

describe("LevelRing", () => {
  it("shows skills to the next level and the pace", () => {
    const out = text(renderToStaticMarkup(createElement(LevelRing, { current: current() })));
    expect(out).toContain("3/6");
    expect(out).toContain("3 skills to Level 3");
    expect(out).toContain("At this pace: about 5 weeks");
  });

  it("omits the pace line when the backend has no honest estimate", () => {
    const out = text(
      renderToStaticMarkup(createElement(LevelRing, { current: current({ pace_weeks: null }) })),
    );
    expect(out).not.toContain("At this pace");
  });

  it("words the last level and a finished level", () => {
    const last = text(
      renderToStaticMarkup(
        createElement(LevelRing, {
          current: current({ has_next_level: false, skills_remaining: 1 }),
        }),
      ),
    );
    expect(last).toContain("1 skill to finish the pathway");
    const done = text(
      renderToStaticMarkup(
        createElement(LevelRing, { current: current({ required_passed: 6, required_total: 6, skills_remaining: 0 }) }),
      ),
    );
    expect(done).toContain("Ready for level review");
  });
});

describe("LevelStrip", () => {
  it("labels Level N of M and marks the current step", () => {
    const journey = {
      current_level: current(),
      levels: ["Grip", "Net", "Serve"].map((name, i) => ({
        level_id: `l${i + 1}`,
        name,
        number: i + 1,
        state: (["done", "current", "upcoming"] as const)[i],
      })),
    } as ParentProgressJourney;
    const html = renderToStaticMarkup(createElement(LevelStrip, { firstName: "Aarav", journey }));
    expect(text(html)).toContain("Level 2 of 3");
    expect(html).toContain('aria-current="step"');
    expect(text(html)).toContain("Current level");
    expect(text(html)).not.toContain("✓");
  });
});

describe("LevelStrip after the last level", () => {
  it("says every level is done instead of a current level", () => {
    const journey = {
      current_level: null,
      pathway_complete: true,
      levels: ["Grip", "Net"].map((name, i) => ({
        level_id: `l${i + 1}`,
        name,
        number: i + 1,
        state: "done" as const,
      })),
    } as unknown as ParentProgressJourney;
    const html = renderToStaticMarkup(createElement(LevelStrip, { firstName: "Aarav", journey }));
    expect(text(html)).toContain("Pathway complete");
    expect(html).not.toContain('aria-current="step"');
  });
});

describe("cross-level progress", () => {
  it("shows higher-level credit alongside a beginner placement", () => {
    const journey = {
      current_level: current({ level_id: "l1", number: 1 }),
      levels: [
        {
          level_id: "l1", name: "Grip", number: 1, state: "current",
          required_passed: 0, required_total: 3, optional_passed: 0, optional_total: 0,
        },
        {
          level_id: "l2", name: "Net", number: 2, state: "upcoming",
          required_passed: 1, required_total: 4, optional_passed: 1, optional_total: 2,
        },
      ],
    } as ParentProgressJourney;
    const out = text(renderToStaticMarkup(createElement(LevelStrip, { firstName: "Maya", journey })));
    expect(out).toContain("Level 1 of 2");
    expect(out).toContain("1/4 required skills passed");
    expect(out).toContain("1/2 optional skills passed");
    const unplaced = { ...journey, current_level: null, pathway_complete: false };
    const pending = text(renderToStaticMarkup(createElement(LevelStrip, { firstName: "Maya", journey: unplaced })));
    expect(pending).toContain("Awaiting level placement");
    expect(pending).toContain("1/4 required skills passed");
  });

  it("uses only required passes for the ring and handles unconfigured levels", () => {
    const render = (fields: Partial<Current>) =>
      text(renderToStaticMarkup(createElement(LevelRing, { current: current(fields) })));
    expect(render({ required_total: 4, required_passed: 1 })).toContain("1/4");
    const empty = render({ required_total: 0, required_passed: 0, skills_remaining: 0 });
    expect(empty).toContain("No required skills configured");
    expect(empty).not.toContain("Ready for level review");
    const legacy = render({ skills_total: 3, skills_done: 3, skills_remaining: 0 });
    expect(legacy).toContain("Your coach reviews level placement");
    expect(legacy).not.toContain("Ready for level review");
  });
});

describe("SkillChecklist", () => {
  it("maps states to parent wording", () => {
    const out = text(
      renderToStaticMarkup(
        createElement(SkillChecklist, {
          skills: [
            { skill_id: "a", name: "Lunge", state: "got_it" },
            { skill_id: "b", name: "Net shot", state: "working_on_it" },
            { skill_id: "c", name: "Net rally", state: "coming_up" },
          ],
        }),
      ),
    );
    expect(out).toContain("Lunge Got it");
    expect(out).toContain("Net shot Working on it");
    expect(out).toContain("Net rally Coming up");
  });
});

describe("RecentWins", () => {
  it("renders skill passes and certificates with a view link", () => {
    const html = renderToStaticMarkup(
      createElement(RecentWins, {
        wins: [
          {
            kind: "skill",
            at: "2026-10-29T18:00:00Z",
            title: "Forecourt movement",
            cert_id: null,
            cert_number: null,
          },
          {
            kind: "certificate",
            at: "2026-10-17T18:00:00Z",
            title: "Grip & Control",
            cert_id: "c1",
            cert_number: "BLN-1",
          },
        ],
        studentId: "s1",
      }),
    );
    expect(text(html)).toContain("Mastered Forecourt movement");
    expect(text(html)).toContain("Certificate: Grip &amp; Control");
    expect(html).toContain('href="/parent/progress/certificates/c1?child=s1"');
  });
});

describe("level colour and coach note", () => {
  it("names the current level's colour on the ring band", () => {
    const html = renderToStaticMarkup(
      createElement(LevelRing, { current: current({ color: "#FB923C" }) }),
    );
    expect(html).toContain('data-testid="current-level-band"');
    expect(text(html)).toContain("Orange level");
  });

  it("quotes the coach on a win that has a note and not on one without", () => {
    const win = {
      kind: "skill" as const,
      at: "2026-10-29T18:00:00Z",
      title: "Lunge",
      cert_id: null,
      cert_number: null,
    };
    const withNote = text(
      renderToStaticMarkup(
        createElement(RecentWins, { wins: [{ ...win, coach_note: "<b>Quick</b> feet" }] }),
      ),
    );
    expect(withNote).toContain("Coach: “&lt;b&gt;Quick&lt;/b&gt; feet”");
    const without = text(renderToStaticMarkup(createElement(RecentWins, { wins: [win] })));
    expect(without).not.toContain("Coach:");
  });
});

describe("formatWinDate", () => {
  const now = new Date("2026-10-31T18:00:00Z");
  it("uses the weekday within the last week, the date before that", () => {
    expect(formatWinDate("2026-10-29T18:00:00Z", now)).toMatch(/^[A-Z][a-z]{2}$/);
    expect(formatWinDate("2026-10-17T18:00:00Z", now)).toMatch(/Oct/);
  });
});

describe("MilestoneList (L5B)", () => {
  it("renders nothing when the academy has milestones off", () => {
    expect(renderToStaticMarkup(createElement(MilestoneList, { milestones: [], firstName: "Maya" }))).toBe("");
  });

  it("labels each milestone, newest first", () => {
    expect(milestoneLabel({ kind: "skills_passed", count: 1 })).toBe("1 skill mastered");
    expect(milestoneLabel({ kind: "levels_completed", count: 2 })).toBe("2 levels completed");
    const html = renderToStaticMarkup(
      createElement(MilestoneList, {
        firstName: "Maya",
        milestones: [
          { kind: "skills_passed", count: 10, reached_at: "2026-10-01T18:00:00Z" },
          { kind: "levels_completed", count: 1, reached_at: "2026-11-01T18:00:00Z" },
        ],
      }),
    );
    expect(html.indexOf("1 level completed")).toBeLessThan(html.indexOf("10 skills mastered"));
    expect(html).toContain("Maya: 10 skills mastered");
  });
});
