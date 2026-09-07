import { describe, expect, it } from "vitest";

import {
  cancellationResultTitle,
  cancellationTimingCopy,
  pendingCancellationLabel,
} from "./cancellation-copy";

// 2026-09-30 23:59:59.999 CDT == 2026-10-01T04:59:59.999Z
const CHICAGO_MONTH_END = "2026-10-01T04:59:59.999Z";

describe("cancellationTimingCopy", () => {
  it("says the enrollment ends today for immediate timing", () => {
    expect(
      cancellationTimingCopy({ effective_timing: "immediate", effective_at: "2026-09-07T12:00:00Z" }, "America/Chicago"),
    ).toBe("Your child's enrollment ends today.");
  });

  it("names the academy-local last day and the unbilled month for end_of_period", () => {
    const copy = cancellationTimingCopy(
      { effective_timing: "end_of_period", effective_at: CHICAGO_MONTH_END },
      "America/Chicago",
    );
    // Renders Sept 30 in Chicago even though the instant is Oct 1 in UTC.
    expect(copy).toMatch(/^Your child keeps their place through .*Sep.* 30/);
    expect(copy).toMatch(/October will not be billed\.$/);
  });

  it("falls back to generic period copy when the API has no effective_at", () => {
    expect(cancellationTimingCopy({ effective_timing: "end_of_period", effective_at: null }, null)).toBe(
      "Your child keeps their place through the end of this billing period.",
    );
  });
});

describe("pendingCancellationLabel", () => {
  it("is null when nothing is pending", () => {
    expect(pendingCancellationLabel(null, "America/Chicago")).toBeNull();
  });

  it("renders the academy-local end date", () => {
    expect(pendingCancellationLabel(CHICAGO_MONTH_END, "America/Chicago")).toMatch(/^Ends .*Sep.* 30/);
  });
});

describe("cancellationResultTitle", () => {
  it("distinguishes a scheduled cancel from an immediate one", () => {
    expect(cancellationResultTitle("pending_cancellation")).toBe("Cancellation scheduled");
    expect(cancellationResultTitle("cancelled")).toBe("Enrollment cancelled");
  });
});
