import { describe, it, expect, vi, beforeEach } from "vitest";
import {
  updateOccurrenceCoachAttendance,
  updateSessionOccurrenceCoach,
  updateOccurrenceReplacement,
} from "./sessions";
import * as client from "../client";

describe("sessions correction client", () => {
  beforeEach(() => vi.restoreAllMocks());

  it("updateOccurrenceCoachAttendance PATCHes coach-attendance", async () => {
    const spy = vi.spyOn(client, "apiFetch").mockResolvedValue({} as never);
    await updateOccurrenceCoachAttendance("o1", { coach_id: "c1", status: "absent" });
    expect(spy).toHaveBeenCalledWith(
      "/admin/session-occurrences/o1/coach-attendance",
      expect.objectContaining({ method: "PATCH" }),
    );
  });

  it("updateSessionOccurrenceCoach PATCHes /coach with required reason", async () => {
    const spy = vi.spyOn(client, "apiFetch").mockResolvedValue({} as never);
    await updateSessionOccurrenceCoach("o1", { actual_coach_id: "c2", reason: "Substituted" });
    expect(spy).toHaveBeenCalledWith(
      "/admin/session-occurrences/o1/coach",
      expect.objectContaining({ method: "PATCH" }),
    );
  });

  it("updateOccurrenceReplacement PATCHes /replacement", async () => {
    const spy = vi.spyOn(client, "apiFetch").mockResolvedValue({} as never);
    await updateOccurrenceReplacement("o1", { replacement_coach_id: "c3" });
    expect(spy).toHaveBeenCalledWith(
      "/admin/session-occurrences/o1/replacement",
      expect.objectContaining({ method: "PATCH" }),
    );
  });
});
