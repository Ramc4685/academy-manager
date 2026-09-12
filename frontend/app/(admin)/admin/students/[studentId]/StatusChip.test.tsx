import { describe, expect, it } from "vitest";

import { chipForStatus } from "./StatusChip";

describe("chipForStatus (#733)", () => {
  it("renders held / reclaim_pending exactly like the class roster does", () => {
    // #733 makes held rows reach this panel at all; they must not read as
    // terminal. The roster (sessions/[id]/RosterPanel.tsx ENROLL_CHIP) shows
    // both hold states as a muted "ON HOLD" — the two surfaces must agree.
    expect(chipForStatus("held")).toEqual({
      variant: "paused",
      label: "ON HOLD",
    });
    expect(chipForStatus("reclaim_pending")).toEqual({
      variant: "paused",
      label: "ON HOLD",
    });
  });

  it("leaves every other status exactly as it was", () => {
    expect(chipForStatus("active")).toEqual({
      variant: "enrolled",
      label: "ACTIVE",
    });
    expect(chipForStatus("paused")).toEqual({
      variant: "paused",
      label: "PAUSED",
    });
    expect(chipForStatus("paid")).toEqual({ variant: "paid", label: "PAID" });
    expect(chipForStatus("succeeded")).toEqual({
      variant: "enrolled",
      label: "SUCCEEDED",
    });
    expect(chipForStatus("unpaid")).toEqual({
      variant: "pending",
      label: "UNPAID",
    });
    expect(chipForStatus("failed")).toEqual({
      variant: "failed",
      label: "FAILED",
    });
    expect(chipForStatus("partially_paid")).toEqual({
      variant: "partial",
      label: "PARTIALLY_PAID",
    });
    expect(chipForStatus("withdrawn")).toEqual({
      variant: "expired",
      label: "WITHDRAWN",
    });
  });
});
