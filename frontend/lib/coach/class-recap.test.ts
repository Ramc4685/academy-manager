import { describe, expect, it } from "vitest";

import {
  creditEveryone,
  nextReportAttempt,
  practiceEligible,
  togglePractice,
  withoutSkill,
} from "./class-recap";

describe("report request id", () => {
  const ids = () => {
    let n = 0;
    return () => `id-${++n}`;
  };

  it("replays the same id when the same report is retried", () => {
    const newId = ids();
    const first = nextReportAttempt(null, "Maya drilled clears", true, newId);
    expect(nextReportAttempt(first, "Maya drilled clears", true, newId).reportId).toBe("id-1");
  });

  it("gets a new id when the text or the AI choice changed", () => {
    const newId = ids();
    const first = nextReportAttempt(null, "Maya drilled clears", true, newId);
    const edited = nextReportAttempt(first, "Maya drilled smashes", true, newId);
    expect(edited.reportId).toBe("id-2");
    expect(nextReportAttempt(edited, "Maya drilled smashes", false, newId).reportId).toBe("id-3");
  });
});

describe("class recap practice helpers", () => {
  it("keeps split drills per child: Maya only X, Leo only Y", () => {
    let practice = togglePractice([], "maya", "skill-x");
    practice = togglePractice(practice, "leo", "skill-y");
    expect(practice).toEqual([
      { student_id: "maya", skill_ids: ["skill-x"] },
      { student_id: "leo", skill_ids: ["skill-y"] },
    ]);
  });

  it("drops a child whose last skill is untoggled, never sends an empty row", () => {
    const practice = togglePractice([{ student_id: "maya", skill_ids: ["skill-x"] }], "maya", "skill-x");
    expect(practice).toEqual([]);
  });

  it("removing a taught skill removes its practice but keeps other children", () => {
    const practice = withoutSkill(
      [
        { student_id: "maya", skill_ids: ["skill-x"] },
        { student_id: "leo", skill_ids: ["skill-x", "skill-y"] },
      ],
      "skill-x",
    );
    expect(practice).toEqual([{ student_id: "leo", skill_ids: ["skill-y"] }]);
  });

  it("credit everyone adds to present/late only, and a second tap toggles nobody off", () => {
    const roster = [
      { student_id: "maya", name: "Maya", attendance: "present" },
      { student_id: "leo", name: "Leo", attendance: "late" },
      { student_id: "ana", name: "Ana", attendance: "absent" },
      { student_id: "kai", name: "Kai", attendance: "unknown" },
    ];
    const start = [{ student_id: "maya", skill_ids: ["skill-y"] }];
    const once = creditEveryone(start, roster, ["skill-x"]);
    expect(once).toEqual([
      { student_id: "maya", skill_ids: ["skill-y", "skill-x"] },
      { student_id: "leo", skill_ids: ["skill-x"] },
    ]);
    expect(creditEveryone(once, roster, ["skill-x"])).toEqual(once);
    // A per-child exception after the bulk credit stays editable.
    expect(togglePractice(once, "leo", "skill-x")).toEqual([
      { student_id: "maya", skill_ids: ["skill-y", "skill-x"] },
    ]);
  });

  it("only present and late children can be credited", () => {
    const roster = ["present", "late", "absent", "unmarked"].map((attendance, i) => ({
      student_id: `s${i}`,
      name: `Kid ${i}`,
      attendance,
    }));
    expect(practiceEligible(roster).map((r) => r.student_id)).toEqual(["s0", "s1"]);
  });
});
