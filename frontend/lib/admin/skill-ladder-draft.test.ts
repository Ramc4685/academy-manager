import { describe, expect, it, vi } from "vitest";

import type { DraftLevel } from "@/lib/api/curriculum";

import {
  ladderDraftErrorMessage,
  ladderDraftIsSavable,
  patchLevel,
  saveLadderDraft,
} from "./skill-ladder-draft";

const levels: DraftLevel[] = [
  {
    sequence: 1,
    name: " Beginner ",
    description: "First steps",
    skills: [
      {
        name: "Grip",
        description: "",
        scoring_type: "ATTEMPT_BASED",
        is_required: true,
        criteria: ["Relaxed grip", "Thumb on the flat side"],
      },
      {
        name: "Serve",
        description: "Short serve",
        scoring_type: "COACH_APPROVAL",
        is_required: false,
        criteria: ["Shuttle lands in the front box"],
      },
    ],
  },
  {
    sequence: 2,
    name: "Improver",
    description: "",
    skills: [
      {
        name: "Clear",
        description: "",
        scoring_type: "RALLY_COUNT",
        is_required: true,
        criteria: ["Reaches the back tramline"],
      },
    ],
  },
];

function fakeApi() {
  let levelsMade = 0;
  let skillsMade = 0;
  return {
    createLevel: vi.fn(async () => ({ level_id: `lvl-${++levelsMade}` })),
    createSkill: vi.fn(async () => ({ skill_id: `sk-${++skillsMade}` })),
    addCriterion: vi.fn(async () => ({ criterion_id: "cr" })),
  };
}

describe("saveLadderDraft", () => {
  it("walks levels, skills and criteria in order through the existing calls", async () => {
    const api = fakeApi();

    await saveLadderDraft("prog-1", levels, 3, api);

    expect(api.createLevel.mock.calls).toEqual([
      ["prog-1", { name: "Beginner", description: "First steps", sequence: 4 }],
      ["prog-1", { name: "Improver", description: "", sequence: 5 }],
    ]);
    expect(api.createSkill.mock.calls).toEqual([
      [
        "lvl-1",
        {
          program_id: "prog-1",
          sequence: 1,
          name: "Grip",
          description: "",
          is_required: true,
          scoring_type: "ATTEMPT_BASED",
        },
      ],
      [
        "lvl-1",
        {
          program_id: "prog-1",
          sequence: 2,
          name: "Serve",
          description: "Short serve",
          is_required: false,
          scoring_type: "COACH_APPROVAL",
        },
      ],
      [
        "lvl-2",
        {
          program_id: "prog-1",
          sequence: 1,
          name: "Clear",
          description: "",
          is_required: true,
          scoring_type: "RALLY_COUNT",
        },
      ],
    ]);
    expect(api.addCriterion.mock.calls).toEqual([
      ["sk-1", { level_id: "lvl-1", program_id: "prog-1", description: "Relaxed grip", display_order: 0 }],
      ["sk-1", { level_id: "lvl-1", program_id: "prog-1", description: "Thumb on the flat side", display_order: 1 }],
      ["sk-2", { level_id: "lvl-1", program_id: "prog-1", description: "Shuttle lands in the front box", display_order: 0 }],
      ["sk-3", { level_id: "lvl-2", program_id: "prog-1", description: "Reaches the back tramline", display_order: 0 }],
    ]);
  });

  it("stops at the first failure so nothing after it is half-saved", async () => {
    const api = fakeApi();
    api.createSkill.mockRejectedValueOnce(new Error("boom"));

    await expect(saveLadderDraft("prog-1", levels, 0, api)).rejects.toThrow("boom");

    expect(api.createLevel).toHaveBeenCalledTimes(1);
    expect(api.addCriterion).not.toHaveBeenCalled();
  });
});

describe("ladderDraftIsSavable", () => {
  it("needs a level, a skill per level and a name on every kept row", () => {
    expect(ladderDraftIsSavable(levels)).toBe(true);
    expect(ladderDraftIsSavable([])).toBe(false);
    expect(ladderDraftIsSavable(patchLevel(levels, 1, (l) => ({ ...l, skills: [] })))).toBe(false);
    expect(ladderDraftIsSavable(patchLevel(levels, 0, (l) => ({ ...l, name: "  " })))).toBe(false);
    expect(
      ladderDraftIsSavable(
        patchLevel(levels, 1, (l) => ({
          ...l,
          skills: [{ ...l.skills[0], criteria: [""] }],
        })),
      ),
    ).toBe(false);
    // A skill with no criteria left is still savable.
    expect(
      ladderDraftIsSavable(
        patchLevel(levels, 1, (l) => ({ ...l, skills: [{ ...l.skills[0], criteria: [] }] })),
      ),
    ).toBe(true);
  });
});

describe("ladderDraftErrorMessage", () => {
  it("maps the AI error codes to plain sentences", () => {
    expect(ladderDraftErrorMessage({ status: 503, code: "Ai.Disabled" })).toBe(
      "AI drafting is not enabled for this academy yet",
    );
    expect(ladderDraftErrorMessage({ status: 429, code: "Ai.MonthlyCapReached" })).toBe(
      "This academy has used its AI drafts for the month",
    );
    expect(ladderDraftErrorMessage({ status: 502, code: "Ai.ProviderError" })).toBe(
      "The draft could not be read, try again",
    );
    expect(ladderDraftErrorMessage(new Error("network"))).toBe(
      "The draft could not be made, try again",
    );
    expect(ladderDraftErrorMessage(undefined)).toBe("The draft could not be made, try again");
  });
});

describe("patchLevel", () => {
  it("replaces one level and leaves the others untouched", () => {
    const next = patchLevel(levels, 0, (l) => ({ ...l, name: "Starter" }));
    expect(next[0].name).toBe("Starter");
    expect(next[1]).toBe(levels[1]);
    expect(levels[0].name).toBe(" Beginner ");
  });
});
