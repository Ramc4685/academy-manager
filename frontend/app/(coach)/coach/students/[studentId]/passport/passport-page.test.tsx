import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it, vi } from "vitest";

vi.mock("next/navigation", () => ({
  useParams: () => ({ studentId: "tej" }),
  useSearchParams: () => new URLSearchParams(),
}));

import type { CoachPassport, SkillPassportEntry } from "@/lib/api/curriculum";
import { passportLevelLine } from "@/lib/coach/passport";

import CoachStudentPassportPage from "./page";

const skill = (id: string, status: SkillPassportEntry["status"]): SkillPassportEntry => ({
  skill_id: id,
  level_id: "lvl-2",
  program_id: "prog",
  skill_name: id,
  skill_description: "",
  sequence: 1,
  is_required: true,
  status,
  last_test_passed: null,
  last_tested_at: null,
  test_attempt_count: 0,
});

const PLACED: CoachPassport = {
  student_id: "tej",
  student_name: "Tej Walkin",
  placed: true,
  level_name: "Grip & Control",
  level_sequence: 2,
  passed_count: 4,
  total_count: 6,
  required_remaining: 2,
  passport: [skill("a", "PASSED"), skill("b", "PRACTICING")],
};

function render(passport: CoachPassport): string {
  const client = new QueryClient();
  client.setQueryData(["coach", "passport", "tej", "default"], passport);
  return renderToStaticMarkup(
    <QueryClientProvider client={client}>
      <CoachStudentPassportPage />
    </QueryClientProvider>,
  );
}

describe("coach passport page", () => {
  it("names an unplaced child and says they are not placed yet", () => {
    const html = render({
      ...PLACED,
      placed: false,
      level_name: null,
      level_sequence: null,
      passed_count: 0,
      total_count: 0,
      required_remaining: 0,
      passport: [],
    });
    expect(html).toContain("Tej Walkin");
    expect(html).toContain("Not placed in a level yet");
    expect(html).not.toContain("Recommend Level Up");
    expect(html).not.toContain("Student tej");
  });

  it("shows the level, the X of Y count and how many required skills remain", () => {
    const html = render(PLACED);
    expect(html).toContain("Level 2 · Grip &amp; Control · 4 of 6 passed");
    expect(html).toMatch(/data-testid="passport-required-remaining"[^>]*>2 required skills to go/);
  });

  it("says not found, with no Retry, when the passport 404s (S13 persona follow-up)", () => {
    const client = new QueryClient({ defaultOptions: { queries: { retryOnMount: false } } });
    client
      .getQueryCache()
      .build(client, { queryKey: ["coach", "passport", "tej", "default"] })
      .setState({ status: "error", error: Object.assign(new Error("Not found"), { status: 404 }) });
    const html = renderToStaticMarkup(
      <QueryClientProvider client={client}>
        <CoachStudentPassportPage />
      </QueryClientProvider>,
    );
    expect(html).toContain("couldn&#x27;t find this child");
    expect(html).not.toContain("Try again");
  });

  it("drops the remaining line once every required skill is passed", () => {
    const html = render({ ...PLACED, required_remaining: 0 });
    expect(html).not.toContain("required skill");
  });
});

describe("passportLevelLine", () => {
  it("does not repeat a level name that is just 'Level N'", () => {
    expect(passportLevelLine({ ...PLACED, level_name: "Level 2" })).toBe("Level 2 · 4 of 6 passed");
  });
});
