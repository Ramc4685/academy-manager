import { renderToStaticMarkup } from "react-dom/server";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { describe, expect, it, vi } from "vitest";

vi.mock("@/lib/api/coach", () => ({
  markCoachSkillMastered: vi.fn(),
  unmarkCoachSkillMastered: vi.fn(),
}));
vi.mock("@/lib/api/curriculum", () => ({ getCoachSessionSkillBoard: vi.fn() }));

import type { SkillBoard } from "@/lib/api/curriculum";
import { queryKeys } from "@/lib/query/keys";
import { TapSkillsWorkspace } from "./TapSkillsWorkspace";

const passed = { status: "PASSED" as const, last_updated_at: null };
const practicing = { status: "PRACTICING" as const, last_updated_at: null };

function board(overrides: Partial<SkillBoard> = {}): SkillBoard {
  return {
    program_id: "prog-1",
    program_name: "Pathway",
    unplaced: [],
    groups: [
      {
        level_id: "lvl-1",
        level_name: "Grip & Control",
        sequence: 1,
        skills: [
          { skill_id: "grip", name: "Thumb grip", sequence: 1, is_required: true },
          { skill_id: "rally", name: "Basic rally", sequence: 2, is_required: true },
        ],
        students: [
          {
            student_id: "s1",
            student_name: "Avery Test",
            statuses: { grip: passed, rally: practicing },
            required_passed: 1,
            required_total: 2,
            total_passed: 1,
            total_count: 2,
            level_up_status: null,
          },
          {
            student_id: "s2",
            student_name: "Blake Test",
            statuses: { grip: passed, rally: passed },
            required_passed: 2,
            required_total: 2,
            total_passed: 2,
            total_count: 2,
            level_up_status: "RECOMMENDED",
          },
        ],
      },
    ],
    ...overrides,
  };
}

function html(data: SkillBoard) {
  const client = new QueryClient();
  client.setQueryData(queryKeys.coach.skillBoard("sess-1"), data);
  return renderToStaticMarkup(
    <QueryClientProvider client={client}>
      <TapSkillsWorkspace occurrenceId="occ-1" sessionId="sess-1" date="2026-10-30" />
    </QueryClientProvider>,
  );
}

describe("TapSkillsWorkspace", () => {
  it("opens on the first skill someone still needs and marks who has it", () => {
    const out = html(board());
    expect(out).toContain("Who got “Basic rally”?");
    expect(out).toContain("Level 1 · Grip &amp; Control");
    // Avery still needs it, Blake has it and is waiting to move up.
    expect(out.match(/>Tap</g)).toHaveLength(1);
    expect(out.match(/>Got it</g)).toHaveLength(1);
    expect(out).toContain("All skills done · moves up this evening");
    expect(out).toContain("1 of 2 skills");
  });

  it("points the coach at placement when nobody is on a level", () => {
    const out = html(board({ groups: [], unplaced: [{ student_id: "s3", student_name: "C" }] }));
    expect(out).toContain("No one in this class is placed on a level yet");
  });
});
