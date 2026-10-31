import { describe, expect, it } from "vitest";

import { describeQueuedMutation } from "./mutation-label";
import type { QueuedMutation } from "./queue";

function mutation(
  payload: Record<string, unknown>,
  labels?: QueuedMutation["labels"],
): QueuedMutation {
  return {
    mutation_id: "m1",
    endpoint: "/coach/attendance",
    payload,
    labels,
    status: "needs_review",
    attempts: 1,
    created_at: "2026-09-20T10:00:00.000Z",
  };
}

describe("describeQueuedMutation", () => {
  it("names the student and the class instead of printing ids (#841)", () => {
    const text = describeQueuedMutation(
      mutation(
        { student_id: "stu-204", session_id: "sess-101", status: "present" },
        { student_full_name: "Jane Doe", session_title: "U10 Tuesday" },
      ),
    );

    expect(text).toContain("Jane Doe");
    expect(text).toContain("U10 Tuesday");
    expect(text).not.toContain("stu-204");
    expect(text).not.toContain("sess-101");
  });

  it("reads present/absent as words, not as a raw status token", () => {
    const text = describeQueuedMutation(
      mutation(
        { student_id: "stu-204", session_id: "sess-101", status: "absent" },
        { student_full_name: "Jane Doe", session_title: "U10 Tuesday" },
      ),
    );

    expect(text).toBe("Marked Jane Doe absent in U10 Tuesday");
  });

  it("falls back to a neutral phrase for marks queued before labels existed", () => {
    // Rows already sitting in a coach's IndexedDB carry no labels; they must
    // still read as English rather than leaking the ids they do have.
    const text = describeQueuedMutation(
      mutation({ student_id: "stu-204", session_id: "sess-101", status: "present" }),
    );

    expect(text).toBe("Attendance mark (present)");
    expect(text).not.toContain("stu-204");
  });

  it("degrades to a generic label when the payload is unrecognisable", () => {
    expect(describeQueuedMutation(mutation({}))).toBe("Attendance mark");
  });
});
