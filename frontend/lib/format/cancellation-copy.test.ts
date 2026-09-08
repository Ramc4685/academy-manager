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

  it("disagrees with the viewer's zone when no academy zone is passed", () => {
    // Issue #675 follow-up: the admin roster used to pass null here, so an
    // admin browsing from a zone east of the academy read "Ends Oct 1" for a
    // child whose last day is Sep 30. Pinning the behaviour makes the
    // regression loud if a caller ever drops the zone again.
    expect(pendingCancellationLabel(CHICAGO_MONTH_END, "UTC")).toMatch(/^Ends .*Oct.* 1/);
    expect(pendingCancellationLabel(CHICAGO_MONTH_END, "America/Chicago")).not.toEqual(
      pendingCancellationLabel(CHICAGO_MONTH_END, "UTC"),
    );
  });
});

describe("cancellationResultTitle", () => {
  it("distinguishes a scheduled cancel from an immediate one", () => {
    expect(cancellationResultTitle("pending_cancellation")).toBe("Cancellation scheduled");
    expect(cancellationResultTitle("cancelled")).toBe("Enrollment cancelled");
  });
});
