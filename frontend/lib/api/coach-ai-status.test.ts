import { beforeEach, describe, expect, it, vi } from "vitest";

import * as client from "./client";
import { draftTechniqueObservation, getCoachAiStatus } from "./coach";

// B6: the skill-notes panel gates its AI draft box on this read. It must be a
// coach-persona route, or a coach-only user (the feature's main user) gets a
// 404 from the admin status route and never sees the box.
describe("coach AI endpoints", () => {
  beforeEach(() => vi.restoreAllMocks());

  it("reads the AI status from the coach persona", async () => {
    const spy = vi.spyOn(client, "apiFetch").mockResolvedValue({ enabled: true } as never);

    await expect(getCoachAiStatus()).resolves.toEqual({ enabled: true });

    expect(spy).toHaveBeenCalledWith("/coach/ai/status", { method: "GET" });
  });

  it("posts the observation text only", async () => {
    const spy = vi.spyOn(client, "apiFetch").mockResolvedValue({} as never);

    await draftTechniqueObservation("stu 1", "flat thumb");

    expect(spy).toHaveBeenCalledWith("/coach/students/stu%201/technique-observation-draft", {
      method: "POST",
      body: JSON.stringify({ observation: "flat thumb" }),
    });
  });
});
