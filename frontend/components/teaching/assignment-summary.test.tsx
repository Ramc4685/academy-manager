import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it } from "vitest";

import type { LessonCard, LevelTeachingGroup } from "@/lib/api/coach";

import { AssignmentSummary } from "./assignment-summary";

const CARD: LessonCard = {
  card_id: "c-1",
  lesson_number: 3,
  title: "Grip ladders",
  goal_summary: "Hold the grip",
  teaching_points: ["Thumb behind the handle"],
  equipment: [],
  activity_summary: "",
  safety_notes: [],
  source: "",
  module_name: "",
  lesson_range: "",
  page_hint: null,
  resource_links: [],
};

function group(overrides: Partial<LevelTeachingGroup> = {}): LevelTeachingGroup {
  return {
    level_id: "l2",
    level_name: "Rallying",
    level_sequence: 2,
    youtube_links: [],
    lesson_card: CARD,
    students: [
      { student_id: "a", student_name: "Alice Fake", next_skill: null, focus: "practice" },
      { student_id: "b", student_name: "Bo Fake", next_skill: null, focus: "practice" },
    ],
    history_known: true,
    assignment: {
      card: CARD,
      cue: "Thumb behind the handle",
      need_count: 1,
      last_taught_at: null,
      is_repeat: false,
      variations: [
        { student_id: "b", student_name: "Bo Fake", skill_id: "s", skill_name: "Clear" },
      ],
    },
    reinforcement: {
      card: { ...CARD, title: "Footwork basics" },
      cue: null,
      need_count: 0,
      last_taught_at: null,
      is_repeat: false,
      variations: [],
    },
    ...overrides,
  };
}

describe("AssignmentSummary", () => {
  it("says who the drill is for, the cue, variations and the warm-up", () => {
    const html = renderToStaticMarkup(<AssignmentSummary group={group()} />).replace(
      /<!-- -->/g,
      "",
    );
    expect(html).toContain("Cue: Thumb behind the handle");
    expect(html).toContain("For 1 of 2 children. Not done by this group yet.");
    expect(html).toContain("Bo Fake: Clear");
    expect(html).toContain("Warm-up from the level below: Footwork basics");
    expect(html).not.toContain("plan-repeat-2");
  });

  it("separates unknown history from a dated last lesson and flags a repeat", () => {
    const unknown = renderToStaticMarkup(
      <AssignmentSummary group={group({ history_known: false })} />,
    );
    expect(unknown).toContain("No delivery history yet for this group.");
    const base = group();
    const repeat = renderToStaticMarkup(
      <AssignmentSummary
        group={{
          ...base,
          assignment: {
            ...base.assignment!,
            is_repeat: true,
            // A Monday 6:30pm Chicago class: still Monday in the session zone.
            last_taught_at: "2026-11-24T00:30:00Z",
          },
        }}
        timezone="America/Chicago"
      />,
    );
    expect(repeat).toContain("Last worked on Mon, Nov 23.");
    expect(repeat).toContain("plan-repeat-2");
  });

  it("renders nothing without an assignment", () => {
    expect(renderToStaticMarkup(<AssignmentSummary group={group({ assignment: null })} />)).toBe("");
  });
});
