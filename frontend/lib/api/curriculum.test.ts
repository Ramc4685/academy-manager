import { beforeEach, describe, expect, it, vi } from "vitest";

import * as client from "./client";
import {
  buildCreateSkillBody,
  createProgram,
  createSkill,
  getAdminPathwayDashboard,
  listPrograms,
  reorderLevels,
  reorderSkills,
  retireLevel,
  retireSkill,
  revokeCertificate,
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

  it("carries the level's program_id and leaves numbering to the server", () => {
    const body = buildCreateSkillBody({ program_id: "prog-1" }, form);

    expect(body).toEqual({
      program_id: "prog-1",
      name: "Forehand clear",
      description: "",
      is_required: true,
      scoring_type: "ATTEMPT_BASED",
    });
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
    const body = buildCreateSkillBody({ program_id: "prog-1" }, form);

    await createSkill("level-1", body);

    expect(spy.mock.calls[0]?.[0]).toBe("/admin/levels/level-1/skills");
    const sent = JSON.parse(String(spy.mock.calls[0]?.[1]?.body));
    expect(sent).toMatchObject({ program_id: "prog-1" });
    expect(sent).not.toHaveProperty("sequence");
  });
});

describe("retire, reorder and revoke endpoints", () => {
  beforeEach(() => vi.restoreAllMocks());

  it("retires by setting is_active false and reorders with the full id list", async () => {
    const spy = vi.spyOn(client, "apiFetch").mockResolvedValue({} as never);

    await retireLevel("l1");
    await retireSkill("s1");
    await reorderLevels("p1", ["l2", "l1"]);
    await reorderSkills("l1", ["s2", "s1"]);
    await revokeCertificate("stu 1", "c1", "approved by mistake");

    expect(spy.mock.calls.map(([path, init]) => [path, init?.method, init?.body])).toEqual([
      ["/admin/levels/l1", "PUT", '{"is_active":false}'],
      ["/admin/skills/s1", "PUT", '{"is_active":false}'],
      ["/admin/programs/p1/levels/order", "PUT", '{"ids":["l2","l1"]}'],
      ["/admin/levels/l1/skills/order", "PUT", '{"ids":["s2","s1"]}'],
      [
        "/admin/students/stu%201/certificates/c1/revoke",
        "POST",
        '{"reason":"approved by mistake"}',
      ],
    ]);
  });

  it("scopes the pathway dashboard to a program only when given one", async () => {
    const spy = vi.spyOn(client, "apiFetch").mockResolvedValue({} as never);

    await getAdminPathwayDashboard();
    await getAdminPathwayDashboard("p 1");

    expect(spy.mock.calls.map(([path]) => path)).toEqual([
      "/admin/pathway/dashboard",
      "/admin/pathway/dashboard?program_id=p%201",
    ]);
  });
});
