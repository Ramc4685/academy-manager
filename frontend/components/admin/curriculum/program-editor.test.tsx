import { renderToStaticMarkup } from "react-dom/server";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { describe, expect, it, vi } from "vitest";

vi.mock("@/lib/api/curriculum", async (importOriginal) => {
  const real = await importOriginal<typeof import("@/lib/api/curriculum")>();
  return { ...real, getFullPathway: vi.fn(), getAdminPathwayDashboard: vi.fn() };
});
vi.mock("@/components/admin/curriculum/skill-ladder-draft-card", () => ({
  SkillLadderDraftCard: () => null,
}));

import type { FullPathway, PathwayDashboard } from "@/lib/api/curriculum";
import { queryKeys } from "@/lib/query/keys";
import { ProgramEditor, swapped } from "./program-editor";

function level(id: string, sequence: number, skillIds: string[]) {
  return {
    level: {
      level_id: id,
      program_id: "p1",
      sequence,
      name: `Level ${id}`,
      description: "",
      color: null,
      display_color: "#2563EB",
      is_active: true,
    },
    skills: skillIds.map((skillId, i) => ({
      skill: {
        skill_id: skillId,
        level_id: id,
        sequence: i + 1,
        name: `Skill ${skillId}`,
        description: "",
        is_required: true,
        scoring_type: "ATTEMPT_BASED",
        pass_threshold_pct: 0,
        is_active: true,
      },
      criteria: [],
      external_refs: [],
    })),
  };
}

function render(playerCounts: Record<string, number> | null) {
  const client = new QueryClient();
  client.setQueryData(["admin", "pathway", "p1"], {
    program: { program_id: "p1", name: "Juniors", sport: "badminton", description: "" },
    levels: [level("l1", 1, ["s1", "s2"]), level("l2", 2, [])],
  } as unknown as FullPathway);
  client.setQueryData(queryKeys.admin.lessonCards("p1"), { count: 0, cards: [] });
  if (playerCounts) {
    client.setQueryData([...queryKeys.admin.pathwayDashboard(), "p1"], {
      levels: Object.entries(playerCounts).map(([level_id, player_count]) => ({
        level_id,
        player_count,
      })),
    } as unknown as PathwayDashboard);
  }
  return renderToStaticMarkup(
    <QueryClientProvider client={client}>
      <ProgramEditor programId="p1" />
    </QueryClientProvider>,
  );
}

/** Whether the button whose markup ends `part` carries the disabled attribute. */
function isDisabled(part: string): boolean {
  return part.slice(part.lastIndexOf("<button")).includes('disabled=""');
}

describe("ProgramEditor retire and reorder", () => {
  it("allows retiring only a level nobody is on, and says why not", () => {
    const out = render({ l1: 3, l2: 0 });
    const retires = out.split("Retire level</button>");
    expect(retires).toHaveLength(3);
    expect(isDisabled(retires[0])).toBe(true);
    expect(isDisabled(retires[1])).toBe(false);
    expect(out).toContain("3 players on this level: move them before retiring it");
  });

  it("keeps Retire level off until the player counts load", () => {
    const out = render(null);
    for (const part of out.split("Retire level</button>").slice(0, -1)) {
      expect(isDisabled(part)).toBe(true);
    }
  });

  it("disables moving past either end and offers a Retire per skill", () => {
    const out = render({ l1: 0, l2: 0 });
    expect(out).toMatch(/aria-label="Move level Level l1 up" disabled=""/);
    expect(out).not.toMatch(/aria-label="Move level Level l1 down" disabled=""/);
    expect(out).toMatch(/aria-label="Move level Level l2 down" disabled=""/);
    expect(out).toMatch(/aria-label="Move skill Skill s2 down" disabled=""/);
    expect(out.match(/>Retire<\/button>/g)).toHaveLength(2);
  });
});

describe("ProgramEditor required toggle (S56)", () => {
  it("lets the owner untick Required on an existing skill", () => {
    const out = render({ l1: 0, l2: 0 });
    expect(out).toContain('data-testid="skill-required-s1"');
    expect(out).toContain("a child can move up a level without this skill");
  });
});

describe("swapped", () => {
  it("moves one id a place up or down", () => {
    expect(swapped(["a", "b", "c"], 1, -1)).toEqual(["b", "a", "c"]);
    expect(swapped(["a", "b", "c"], 1, 1)).toEqual(["a", "c", "b"]);
  });
});
