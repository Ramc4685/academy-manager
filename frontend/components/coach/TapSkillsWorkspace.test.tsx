import { renderToStaticMarkup } from "react-dom/server";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { describe, expect, it, vi } from "vitest";

vi.mock("@/lib/api/coach", () => ({
  markCoachSkillMastered: vi.fn(),
  unmarkCoachSkillMastered: vi.fn(),
  setCoachMasteryNote: vi.fn(),
  getCoachAiStatus: vi.fn(),
}));
vi.mock("@/lib/api/curriculum", () => ({ getCoachSessionSkillBoard: vi.fn() }));

import type { SkillBoard } from "@/lib/api/curriculum";
import { queryKeys } from "@/lib/query/keys";
import { MasteryNote, TapSkillsWorkspace } from "./TapSkillsWorkspace";

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
          { skill_id: "grip", name: "Thumb grip", sequence: 1, is_required: true, criteria: [] },
          {
            skill_id: "rally",
            name: "Basic rally",
            sequence: 2,
            is_required: true,
            criteria: ["Thumb is flat on back of handle", "Elbow in front of body"],
          },
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

describe("TapSkillsWorkspace program selection", () => {
  it("reads the board for the page's program_id, not the default curriculum", () => {
    const client = new QueryClient();
    client.setQueryData(
      queryKeys.coach.skillBoard("sess-1", "prog-2"),
      board({ program_id: "prog-2", program_name: "Second" }),
    );
    const out = renderToStaticMarkup(
      <QueryClientProvider client={client}>
        <TapSkillsWorkspace occurrenceId="occ-1" sessionId="sess-1" date="2026-10-30" programId="prog-2" />
      </QueryClientProvider>,
    );
    expect(out).toContain("coach-tap-skills");
  });
});

describe("TapSkillsWorkspace coach note", () => {
  const today = { status: "PASSED" as const, last_updated_at: new Date().toISOString() };

  function withRally(cell: Record<string, unknown>) {
    const b = board();
    b.groups[0].color = "#FB923C";
    b.groups[0].students[1].statuses = { grip: passed, rally: { ...today, ...cell } };
    return b;
  }

  it("offers a note on today's win and shows a saved note as a quote", () => {
    expect(html(withRally({}))).toContain("+ Note for Blake Test&#x27;s parents");
    const out = html(withRally({ coach_note: "Quick feet" }));
    expect(out).toContain("“Quick feet”");
    expect(out).toContain('aria-label="Edit the note for Blake Test&#x27;s parents"');
    expect(out).toContain('aria-label="Remove the note for Blake Test&#x27;s parents"');
  });

  it("reads offset-less timestamps from Mongo as UTC", () => {
    const naiveUtc = (hoursAgo: number) =>
      new Date(Date.now() - hoursAgo * 3600_000).toISOString().replace("Z", "");
    expect(html(withRally({ last_updated_at: naiveUtc(23) }))).toContain("+ Note for");
    expect(html(withRally({ last_updated_at: naiveUtc(25) }))).not.toContain("Note for");
  });

  it("offers no note on an older win", () => {
    expect(html(board())).not.toContain("Note for");
  });

  it("paints the level with its colour", () => {
    expect(html(withRally({}))).toMatch(/background:\s*#FB923C/i);
  });
});

describe("MasteryNote criterion quick-tags", () => {
  const criteria = ["Thumb is flat on back of handle", "Elbow in front of body"];
  const noop = () => undefined;

  function editor(draft: string, crit = criteria) {
    return renderToStaticMarkup(
      <MasteryNote
        studentName="Blake Test"
        criteria={crit}
        note=""
        editing
        draft={draft}
        saving={false}
        onDraft={noop}
        onEdit={noop}
        onCancel={noop}
        onSave={noop}
        onRemove={noop}
      />,
    );
  }

  it("shows each criterion as a touch-sized chip, pressed when the draft already says it", () => {
    const out = editor("Nailed it today: elbow in front of body.");
    expect(out).toContain('aria-label="Tap what Blake Test nailed"');
    expect(out).toMatch(/aria-pressed="false"[^>]*>Thumb is flat on back of handle</);
    expect(out).toMatch(/aria-pressed="true"[^>]*>Elbow in front of body</);
    expect(out.match(/min-h-touch rounded-full/g)).toHaveLength(2);
    expect(out).toContain('value="Nailed it today: elbow in front of body."');
  });

  it("disables a chip that no longer fits the note", () => {
    const out = editor("", ["x".repeat(140)]);
    expect(out).toMatch(/aria-pressed="false" disabled=""/);
  });

  it("shows no chip row for a skill without criteria", () => {
    expect(editor("", [])).not.toContain("Tap what");
  });
});
