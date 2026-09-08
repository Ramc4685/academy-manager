import { describe, expect, it } from "vitest";

import type { ApiError } from "@/lib/api/client";

import {
  ENROLLMENT_ENDED_CODE,
  isWithdrawn,
  recommendErrorMessage,
  reviewErrorMessage,
} from "./level-up-review";

function apiError(status: number, code?: string): ApiError {
  const err = new Error("Request failed") as ApiError;
  err.status = status;
  err.code = code;
  return err;
}

describe("isWithdrawn", () => {
  it("is true only when the queue explicitly says the enrollment ended", () => {
    expect(isWithdrawn({ enrollment_active: false })).toBe(true);
    expect(isWithdrawn({ enrollment_active: true })).toBe(false);
    // Older responses (and the coach recommend payload) omit the field:
    // treat as live so the approve button is not disabled on stale data.
    expect(isWithdrawn({})).toBe(false);
  });
});

describe("reviewErrorMessage", () => {
  it("explains the enrollment-ended 409 and points at reject", () => {
    const message = reviewErrorMessage(apiError(409, ENROLLMENT_ENDED_CODE));
    expect(message).toMatch(/withdrawn/i);
    expect(message).toMatch(/reject/i);
    expect(message).not.toMatch(/already reviewed/i);
  });

  it("keeps the already-reviewed wording for the other 409", () => {
    expect(
      reviewErrorMessage(apiError(409, "StudentProgress.RecommendationAlreadyReviewed")),
    ).toMatch(/already reviewed/i);
    expect(reviewErrorMessage(apiError(409))).toMatch(/already reviewed/i);
  });

  it("keeps the 404 and fallback wording", () => {
    expect(reviewErrorMessage(apiError(404))).toMatch(/no longer exists/i);
    expect(reviewErrorMessage(new Error("boom"))).toBe("boom");
    expect(reviewErrorMessage(undefined)).toBe("Could not update this recommendation.");
  });
});

describe("recommendErrorMessage", () => {
  it("names the ended enrollment for the coach's 409", () => {
    const message = recommendErrorMessage(apiError(409, ENROLLMENT_ENDED_CODE));
    expect(message).toMatch(/no longer has an active enrollment/i);
    expect(message).not.toMatch(/failed to submit/i);
  });

  it("keeps the generic wording for every other failure", () => {
    expect(recommendErrorMessage(apiError(409))).toBe("Failed to submit recommendation.");
    expect(recommendErrorMessage(apiError(500))).toBe("Failed to submit recommendation.");
    expect(recommendErrorMessage(new Error("boom"))).toBe("Failed to submit recommendation.");
    expect(recommendErrorMessage(undefined)).toBe("Failed to submit recommendation.");
  });
});
