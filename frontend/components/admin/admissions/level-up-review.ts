import type { LevelUpRecommendation } from "@/lib/api/curriculum";
import type { ApiError } from "@/lib/api/client";

/** Backend code raised when approving a student with no live enrollment (#673). */
export const ENROLLMENT_ENDED_CODE = "StudentProgress.EnrollmentEnded";

export const WITHDRAWN_APPROVE_HINT =
  "This student no longer has an active or paused enrollment. Level-ups cannot be approved for withdrawn students; reject to clear the row.";

/** A recommendation for a student who has since withdrawn or been cancelled. */
export function isWithdrawn(rec: Pick<LevelUpRecommendation, "enrollment_active">): boolean {
  return rec.enrollment_active === false;
}

export function reviewErrorMessage(err: unknown): string {
  const apiErr = err as ApiError | undefined;
  const status = apiErr?.status;
  if (status === 409 && apiErr?.code === ENROLLMENT_ENDED_CODE) {
    return "This student has withdrawn since the recommendation was made, so it cannot be approved. Reject it to clear the queue.";
  }
  if (status === 409) {
    return "This recommendation was already reviewed by someone else. The queue has been refreshed.";
  }
  if (status === 404) {
    return "This recommendation no longer exists. The queue has been refreshed.";
  }
  return err instanceof Error && err.message ? err.message : "Could not update this recommendation.";
}

/**
 * Coach passport counterpart of `reviewErrorMessage` (#673): the recommend
 * call raises the same `EnrollmentEnded` 409 when the withdrawal landed
 * between the passport load and the tap.
 */
export function recommendErrorMessage(err: unknown): string {
  const apiErr = err as ApiError | undefined;
  if (apiErr?.status === 409 && apiErr?.code === ENROLLMENT_ENDED_CODE) {
    return "This student no longer has an active enrollment, so a level-up cannot be recommended.";
  }
  return "Failed to submit recommendation.";
}
