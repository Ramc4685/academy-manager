import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it } from "vitest";

import type { ClassRecapView } from "@/lib/api/class-recap";

import { ClassRecapBody } from "./ClassRecapPanel";

const VIEW: ClassRecapView = {
  occurrence_id: "occ-1",
  class_starts_at: "2026-11-18T20:00:00Z",
  can_edit: true,
  can_resolve: false,
  ai_enabled: true,
  revision: 2,
  source: "direct",
  updated_at: "2026-11-18T21:00:00Z",
  taught_skills: [
    { skill_id: "sk-x", name: "Forehand grip", level_name: "L1" },
    { skill_id: "sk-y", name: "Jump smash", level_name: "L3" },
  ],
  practice: [
    { student_id: "maya", skill_ids: ["sk-x"] },
    { student_id: "leo", skill_ids: ["sk-y"] },
  ],
  roster: [
    { student_id: "maya", name: "Maya Lopez", attendance: "present" },
    { student_id: "leo", name: "Leo Chen", attendance: "late" },
    { student_id: "ana", name: "Ana Diaz", attendance: "absent" },
  ],
  skill_options: [{ skill_id: "sk-z", name: "Serve", level_name: "L2" }],
  reports: [],
};

function render(overrides: Partial<ClassRecapView> = {}, skillsHref?: string): string {
  return renderToStaticMarkup(
    <QueryClientProvider client={new QueryClient()}>
      <ClassRecapBody view={{ ...VIEW, ...overrides }} skillsHref={skillsHref} />
    </QueryClientProvider>,
  );
}

function pressed(html: string, testId: string): string | null {
  const tag = new RegExp(`<button[^>]*data-testid="${testId}"[^>]*>`).exec(html)?.[0];
  return tag ? (/aria-pressed="(\w+)"/.exec(tag)?.[1] ?? null) : null;
}

describe("ClassRecapPanel", () => {
  it("shows split drills per child: Maya only grip, Leo only smash", () => {
    const html = render();
    expect(pressed(html, "practice-maya-sk-x")).toBe("true");
    expect(pressed(html, "practice-maya-sk-y")).toBe("false");
    expect(pressed(html, "practice-leo-sk-y")).toBe("true");
    expect(pressed(html, "practice-leo-sk-x")).toBe("false");
  });

  it("offers one labelled credit-everyone action over present/late children", () => {
    const html = render();
    expect(html).toContain("Skill to credit to everyone present");
    expect(html).toContain("All taught skills");
    expect(html).toMatch(/data-testid="recap-credit-everyone"[^>]*>Credit everyone present \(2\)/);
    expect(render({ can_edit: false })).not.toContain("recap-credit-everyone");
  });

  it("never offers practice for an absent child", () => {
    const html = render();
    expect(html).not.toContain("practice-ana-");
    expect(html).not.toContain("Ana Diaz");
  });

  it("keeps taught skills when nobody is credited with practice", () => {
    const html = render({ practice: [] });
    expect(html).toContain("Forehand grip");
    expect(html).toContain("Jump smash");
    expect(pressed(html, "practice-maya-sk-x")).toBe("false");
  });

  it("states what optional AI processing does before the coach opts in", () => {
    const html = render();
    expect(html).toContain("Let AI read this report (optional)");
    expect(html).toMatch(/names swapped for codes/);
    expect(html).toMatch(/Passes are never recorded from a report/);
    expect(html).toMatch(/goes to the owner/);
    const box = /<input[^>]*data-testid="recap-report-use-ai"[^>]*>/.exec(html)?.[0] ?? "";
    expect(box).not.toContain("checked");
  });

  it("without AI, the report form only sends to the owner", () => {
    const html = render({ ai_enabled: false });
    expect(html).not.toContain("recap-report-use-ai");
    expect(html).toContain("recap-ai-off-note");
    expect(html).toContain("Send to owner");
  });

  it("is read-only for assistants and admins, with no report form", () => {
    const html = render({ can_edit: false });
    expect(html).toContain("recap-read-only");
    expect(html).not.toContain("recap-save");
    expect(html).not.toContain("recap-report-text");
    expect(html).not.toContain("practice-maya-sk-x");
    expect(html).toContain("Forehand grip");
  });

  it("shows a report's pass claim as a follow-up, never as a pass", () => {
    const html = render({
      can_resolve: true,
      reports: [
        {
          report_id: "r-1",
          is_mine: false,
          text: "Maya passed her grip",
          submitted_at: "2026-11-18T21:00:00Z",
          outcome: "sent_to_owner",
          ai_used: false,
          questions: [],
          pass_claims: [{ student_id: "maya", skill_id: "sk-x" }],
          applied_revision: null,
          resolved_at: null,
        },
      ],
    }, "/coach/sessions/occ-1/skills?date=2026-11-18");
    expect(html).toContain("Maya Lopez passed Forehand grip");
    expect(html).toContain("not recorded as a pass");
    expect(html).toContain("Mark handled");
    expect(html).toMatch(
      /<a[^>]*href="\/coach\/sessions\/occ-1\/skills\?date=2026-11-18"[^>]*data-testid="recap-skills-link"|<a[^>]*data-testid="recap-skills-link"[^>]*href="\/coach\/sessions\/occ-1\/skills\?date=2026-11-18"/,
    );
  });
});
