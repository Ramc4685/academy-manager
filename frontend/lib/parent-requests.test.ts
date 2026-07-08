import { describe, expect, it } from "vitest";

import { requestStatusChipVariant } from "./parent-requests";

describe("requestStatusChipVariant", () => {
  it("maps each known backend status to its Chip variant", () => {
    expect(requestStatusChipVariant("pending")).toBe("pending");
    expect(requestStatusChipVariant("approved")).toBe("approved");
    expect(requestStatusChipVariant("denied")).toBe("denied");
    expect(requestStatusChipVariant("expired")).toBe("expired");
    expect(requestStatusChipVariant("converted")).toBe("converted");
  });

  it("falls back to pending for an unrecognized status", () => {
    expect(requestStatusChipVariant("some_future_status")).toBe("pending");
  });
});
