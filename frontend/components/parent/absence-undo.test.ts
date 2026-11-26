import { describe, expect, it, vi } from "vitest";

vi.mock("@/lib/api/parent", () => ({ withdrawAbsenceNotice: vi.fn() }));

import { absenceReportedToast, canUndoAbsence } from "./absence-undo";

describe("absence Undo (S43)", () => {
  it("puts Undo on the success toast and runs the withdrawal on click", () => {
    const undo = vi.fn();
    const toast = absenceReportedToast(undo);
    expect(toast.title).toBe("Absence reported");
    expect(toast.action?.label).toBe("Undo");
    toast.action?.onClick();
    expect(undo).toHaveBeenCalledTimes(1);
  });

  it("offers Undo only before the class starts", () => {
    const now = Date.parse("2026-11-28T15:00:00Z");
    expect(canUndoAbsence("2026-11-28T16:00:00Z", now)).toBe(true);
    expect(canUndoAbsence("2026-11-28T15:00:00Z", now)).toBe(false);
    expect(canUndoAbsence("2026-11-28T14:00:00Z", now)).toBe(false);
    expect(canUndoAbsence(null, now)).toBe(false);
  });
});
