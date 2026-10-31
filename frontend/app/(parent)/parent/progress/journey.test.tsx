import { createElement } from "react";
import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it } from "vitest";

import type { ParentProgressJourney } from "@/lib/api/parent";

import { LevelRing, LevelStrip, RecentWins, SkillChecklist, formatWinDate } from "./journey";

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
        createElement(LevelRing, { current: current({ skills_done: 6, skills_remaining: 0 }) }),
      ),
    );
    expect(done).toContain("Level 2 done, moving up to Level 3");
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
    expect(text(html)).toContain("Level 1, Grip: done");
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
  it("renders skill passes with the coach note and certificates with a view link", () => {
    const html = renderToStaticMarkup(
      createElement(RecentWins, {
        wins: [
          {
            kind: "skill",
            at: "2026-10-29T18:00:00Z",
            title: "Forecourt movement",
            coach_note: "Much quicker to the net.",
            cert_id: null,
            cert_number: null,
          },
          {
            kind: "certificate",
            at: "2026-10-17T18:00:00Z",
            title: "Grip & Control",
            coach_note: null,
            cert_id: "c1",
            cert_number: "BLN-1",
          },
        ],
      }),
    );
    expect(text(html)).toContain("Mastered Forecourt movement");
    expect(text(html)).toContain("Much quicker to the net.");
    expect(text(html)).toContain("Certificate: Grip &amp; Control");
    expect(html).toContain('href="#certificate-c1"');
  });
});

describe("formatWinDate", () => {
  const now = new Date("2026-10-31T18:00:00Z");
  it("uses the weekday within the last week, the date before that", () => {
    expect(formatWinDate("2026-10-29T18:00:00Z", now)).toMatch(/^[A-Z][a-z]{2}$/);
    expect(formatWinDate("2026-10-17T18:00:00Z", now)).toMatch(/Oct/);
  });
});
