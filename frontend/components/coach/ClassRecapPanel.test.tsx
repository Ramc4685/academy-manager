import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it } from "vitest";

import type { ApiError } from "@/lib/api/client";
import type { ClassRecapView } from "@/lib/api/class-recap";
import { nextReportAttempt } from "@/lib/coach/class-recap";

import { queryKeys } from "@/lib/query/keys";

import {
  afterReportError,
  ClassRecapEditor,
  ClassReportForm,
  refreshTodayRecapFlags,
} from "./ClassRecapPanel";

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
  passes: [],
  roster: [
    { student_id: "maya", name: "Maya Lopez", attendance: "present" },
    { student_id: "leo", name: "Leo Chen", attendance: "late" },
    { student_id: "ana", name: "Ana Diaz", attendance: "absent" },
  ],
  skill_options: [{ skill_id: "sk-z", name: "Serve", level_name: "L2" }],
  reports: [],
};

function render(
  overrides: Partial<ClassRecapView> = {},
  skillsHref?: string,
): string {
  return renderToStaticMarkup(
    <QueryClientProvider client={new QueryClient()}>
      <ClassRecapEditor
        view={{ ...VIEW, ...overrides }}
        skillsHref={skillsHref}
      />
    </QueryClientProvider>,
  );
}

function pressed(html: string, testId: string): string | null {
  const tag = new RegExp(`<button[^>]*data-testid="${testId}"[^>]*>`).exec(
    html,
  )?.[0];
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
    expect(html).toMatch(
      /data-testid="recap-credit-everyone"[^>]*>Credit everyone present \(2\)/,
    );
    expect(render({ can_edit: false })).not.toContain("recap-credit-everyone");
  });

  it("offers a pass per taught skill and locks a saved one with its receipt", () => {
    const html = render({
      passes: [
        { student_id: "maya", skill_id: "sk-x", receipt: "in_progress", added_revision: 2 },
      ],
    });
    expect(pressed(html, "pass-leo-sk-y")).toBe("false");
    expect(html).not.toContain('data-testid="pass-maya-sk-x"');
    expect(html).toContain("✓ Passed: Forehand grip");
    expect(html).toMatch(
      /data-testid="pass-receipt-maya-sk-x"[^>]*>Pass still saving\. Save again to finish it\./,
    );
    expect(html).toMatch(/data-testid="recap-save"[^>]*>Finish saving/);
    expect(html).not.toContain("pass-ana-");
  });

  it("lets the coach take off a pass the skill rules never counted", () => {
    const html = render({
      passes: [
        {
          student_id: "maya",
          skill_id: "sk-x",
          receipt: "not_recorded",
          added_revision: 2,
        },
      ],
    });
    expect(pressed(html, "pass-maya-sk-x")).toBe("true");
    expect(html).toContain("Not counted by the skill rules");
    expect(html).toMatch(/data-testid="recap-save"[^>]*>Save recap/);
  });

  it("shows a recorded pass read-only and no pass offers without edit rights", () => {
    const html = render({
      can_edit: false,
      passes: [
        { student_id: "maya", skill_id: "sk-x", receipt: "recorded", added_revision: 1 },
      ],
    });
    expect(html).toContain("Pass recorded");
    expect(html).not.toContain('data-testid="pass-leo-');
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
    const box =
      /<input[^>]*data-testid="recap-report-use-ai"[^>]*>/.exec(html)?.[0] ??
      "";
    expect(box).not.toContain("checked");
  });

  it("keeps the AI option folded away so the standard report stays the main path", () => {
    const html = render();
    const details =
      /<details[^>]*data-testid="recap-ai-options"[^>]*>/.exec(html)?.[0] ?? "";
    expect(details).not.toBe("");
    expect(details).not.toContain("open");
    expect(html).toContain("More options: AI reading");
    expect(html).toContain("recap-report-submit");
  });

  it("blocks a report while the recap has unsaved edits, so it cannot overwrite them", () => {
    const html = renderToStaticMarkup(
      <QueryClientProvider client={new QueryClient()}>
        <ClassReportForm view={VIEW} recapDirty />
      </QueryClientProvider>,
    );
    expect(html).toContain("recap-report-blocked");
    expect(
      /<button[^>]*data-testid="recap-report-submit"[^>]*>/.exec(html)?.[0],
    ).toContain("disabled");
    expect(render()).not.toContain("recap-report-blocked");
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
    const html = render(
      {
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
      },
      "/coach/sessions/occ-1/skills?date=2026-11-18",
    );
    expect(html).toContain("Maya Lopez passed Forehand grip");
    expect(html).toContain("not recorded as a pass");
    expect(html).toContain("Mark handled");
    expect(html).toMatch(
      /<a[^>]*href="\/coach\/sessions\/occ-1\/skills\?date=2026-11-18"[^>]*data-testid="recap-skills-link"|<a[^>]*data-testid="recap-skills-link"[^>]*href="\/coach\/sessions\/occ-1\/skills\?date=2026-11-18"/,
    );
  });
});

describe("report send failures", () => {
  const conflict = (details: Record<string, unknown>) =>
    Object.assign(new Error("conflict"), { status: 409, details }) as ApiError;

  it("replays the same id on every identical retry while the report is still processing", () => {
    let n = 0;
    const newId = () => `id-${++n}`;
    let attempt = nextReportAttempt(null, "Maya drilled clears", true, newId);
    for (let i = 0; i < 3; i++) {
      const next = afterReportError(conflict({ processing: true }), attempt);
      expect(next.message).toContain("still being read");
      attempt = nextReportAttempt(
        next.attempt,
        "Maya drilled clears",
        true,
        newId,
      );
      expect(attempt.reportId).toBe("id-1");
    }
  });

  it("mints a new id after a 409 that spent the id on a different report", () => {
    let n = 0;
    const newId = () => `id-${++n}`;
    const first = nextReportAttempt(null, "Maya drilled clears", true, newId);
    const next = afterReportError(conflict({ report_id: "id-1" }), first);
    expect(next.attempt).toBeNull();
    expect(
      nextReportAttempt(next.attempt, "Maya drilled clears", true, newId)
        .reportId,
    ).toBe("id-2");
  });
});

describe("refreshTodayRecapFlags", () => {
  it("marks every cached Today list stale so a saved recap drops its shortcut", () => {
    const client = new QueryClient();
    client.setQueryData(queryKeys.coach.today("2026-11-21"), { sessions: [] });
    client.setQueryData(queryKeys.coach.today("2026-11-22"), { sessions: [] });
    client.setQueryData(queryKeys.coach.todayPlan("2026-11-22"), {});
    refreshTodayRecapFlags(client);
    expect(
      client.getQueryState(queryKeys.coach.today("2026-11-21"))?.isInvalidated,
    ).toBe(true);
    expect(
      client.getQueryState(queryKeys.coach.today("2026-11-22"))?.isInvalidated,
    ).toBe(true);
    expect(
      client.getQueryState(queryKeys.coach.todayPlan("2026-11-22"))
        ?.isInvalidated,
    ).toBe(false);
  });
});
