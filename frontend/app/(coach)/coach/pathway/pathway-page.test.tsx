import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it, vi } from "vitest";

import type { CoachPathway } from "@/lib/api/coach";
import { queryKeys } from "@/lib/query/keys";

vi.mock("next/navigation", () => ({ useRouter: () => ({ back: () => {} }) }));

import CoachPathwayPage from "./page";

const LESSON = {
  card_id: "c1",
  lesson_number: 2,
  title: "Ready position",
  goal_summary: "Balanced, racket up",
  teaching_points: ["Feet shoulder width", "Racket in front"],
  equipment: ["rackets", "shuttles"],
  safety_notes: ["space between pairs"],
  activity_summary: "mirror drill in pairs",
  video_url: null,
};

function render(pathway: CoachPathway) {
  const client = new QueryClient();
  client.setQueryData(queryKeys.coach.pathway(), pathway);
  return renderToStaticMarkup(
    <QueryClientProvider client={client}>
      <CoachPathwayPage />
    </QueryClientProvider>,
  );
}

describe("coach What we teach", () => {
  it("opens Level 1 with its description, skills and lesson cards", () => {
    const html = render({
      programs: [
        {
          program_id: "p1",
          name: "Badminton Skill Pathway",
          levels: [
            {
              level_id: "l1",
              sequence: 1,
              name: "Grip and Control",
              description: "Holding the racket and controlling the shuttle.",
              skills: [
                { skill_id: "s1", name: "Thumb grip" },
                { skill_id: "s2", name: "V grip" },
              ],
              lessons: [LESSON],
            },
            { level_id: "l2", sequence: 2, name: "Net and Movement", description: "", skills: [], lessons: [] },
          ],
        },
      ],
    });
    expect(html).toContain("Badminton Skill Pathway · 2 levels");
    expect(html).toMatch(/<details open=""[^>]*>.*Grip and Control/);
    expect(html).toContain("Thumb grip · V grip");
    expect(html).toContain("Goal: Balanced, racket up");
    expect(html).toContain("Feet shoulder width");
    expect(html).toContain("Equipment: rackets, shuttles");
    expect(html).toContain("Safety: space between pairs");
    expect(html).toContain("Activity: mirror drill in pairs");
    expect(html).toContain("No lesson plans for this level yet.");
  });

  it("says what to do when the academy has no levels", () => {
    const html = render({ programs: [] });
    expect(html).toContain("The academy has not set up its levels yet.");
  });
});
