import { renderToStaticMarkup } from "react-dom/server";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { describe, expect, it, vi } from "vitest";

vi.mock("@/lib/api/curriculum", () => ({ updateSkillStatus: vi.fn(), recordTestAttempt: vi.fn() }));

import type { TeachingStudentFocus } from "@/lib/api/coach";
import { StudentFocusRow } from "./student-focus-row";

function passedButton(status: string): string {
  const student: TeachingStudentFocus = {
    student_id: "s1",
    student_name: "Avery Test",
    focus: "practice",
    next_skill: {
      skill_id: "grip",
      name: "Thumb grip",
      sequence: 1,
      level_id: "lvl-1",
      status,
      is_review: false,
      criteria: [],
      youtube_links: [],
    },
  };
  const out = renderToStaticMarkup(
    <QueryClientProvider client={new QueryClient()}>
      <StudentFocusRow student={student} programId="prog-1" sessionId="sess-1" date="2026-11-28" />
    </QueryClientProvider>,
  );
  return /<button[^>]*data-testid="outcome-s1-passed"[^>]*>/.exec(out)![0];
}

describe("StudentFocusRow Passed button", () => {
  it("is not drawn selected for a child who has not passed (bug-08)", () => {
    for (const status of ["NOT_STARTED", "LEARNING", "PRACTICING"]) {
      const button = passedButton(status);
      expect(button).toContain('aria-pressed="false"');
      expect(button).not.toContain("bg-green-600");
    }
  });

  it("is solid only when the skill is passed", () => {
    expect(passedButton("PASSED")).toContain("bg-green-600");
  });
});
