import { beforeEach, describe, expect, it, vi } from "vitest";

import * as client from "./client";
import {
  buildCreateSkillBody,
  createProgram,
  createSkill,
  listPrograms,
  SKILL_SCORING_TYPES,
} from "./curriculum";

describe("skill program endpoints", () => {
  beforeEach(() => vi.restoreAllMocks());

  // /admin/programs belongs to the public page; skill programs must not use it.
  it("lists skill programs from the curriculum path", async () => {
    const spy = vi.spyOn(client, "apiFetch").mockResolvedValue({ programs: [] } as never);

    await listPrograms("acad-1");

    expect(spy.mock.calls[0]?.[0]).toBe("/admin/curriculum/programs?academy_id=acad-1");
  });

  it("creates skill programs on the curriculum path", async () => {
    const spy = vi.spyOn(client, "apiFetch").mockResolvedValue({} as never);

    await createProgram({ name: "Juniors", sport: "badminton", description: "" });

    expect(spy).toHaveBeenCalledWith(
      "/admin/curriculum/programs",
      expect.objectContaining({ method: "POST" }),
    );
  });
});

describe("Add Skill payload", () => {
  beforeEach(() => vi.restoreAllMocks());

  const form = {
    name: "  Forehand clear ",
    description: "",
    is_required: true,
    scoring_type: "ATTEMPT_BASED" as const,
  };

  it("carries the level's program_id and the next sequence", () => {
    const body = buildCreateSkillBody({ program_id: "prog-1" }, [{ sequence: 1 }, { sequence: 4 }], form);

    expect(body).toEqual({
      program_id: "prog-1",
      sequence: 5,
      name: "Forehand clear",
      description: "",
      is_required: true,
      scoring_type: "ATTEMPT_BASED",
    });
  });

  it("starts at sequence 1 for an empty level", () => {
    expect(buildCreateSkillBody({ program_id: "prog-1" }, [], form).sequence).toBe(1);
  });

  it("only offers scoring types the backend accepts", () => {
    expect(SKILL_SCORING_TYPES.map((t) => t.value)).toEqual([
      "ATTEMPT_BASED",
      "CHECKLIST_BASED",
      "COACH_APPROVAL",
      "RALLY_COUNT",
      "TIME_BASED",
      "POINTS_BASED",
    ]);
  });

  it("posts the full body to the level's skills route", async () => {
    const spy = vi.spyOn(client, "apiFetch").mockResolvedValue({} as never);
    const body = buildCreateSkillBody({ program_id: "prog-1" }, [], form);

    await createSkill("level-1", body);

    expect(spy.mock.calls[0]?.[0]).toBe("/admin/levels/level-1/skills");
    expect(JSON.parse(String(spy.mock.calls[0]?.[1]?.body))).toMatchObject({
      program_id: "prog-1",
      sequence: 1,
    });
  });
});
