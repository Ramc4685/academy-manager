import { describe, expect, it } from "vitest";

import { selectedStudentIds, toggleStudent } from "./skill-group-selection";

describe("skill group selection (#1042)", () => {
  const group = ["s-a", "s-b"];

  it("selects the whole group before the coach touches anything", () => {
    expect(selectedStudentIds(null, group)).toEqual(["s-a", "s-b"]);
  });

  it("unchecking every student leaves nobody selected, not the whole group", () => {
    let selection = toggleStudent(null, group, "s-a", false);
    expect(selection).toEqual(["s-b"]);
    selection = toggleStudent(selection, group, "s-b", false);
    expect(selection).toEqual([]);
    expect(selectedStudentIds(selection, group)).toEqual([]);
  });

  it("lets the only student in a one-student group be unchecked and rechecked", () => {
    const empty = toggleStudent(null, ["solo"], "solo", false);
    expect(selectedStudentIds(empty, ["solo"])).toEqual([]);
    expect(toggleStudent(empty, ["solo"], "solo", true)).toEqual(["solo"]);
  });

  it("drops ids that are not in the current group after a refetch", () => {
    expect(selectedStudentIds(["s-a", "gone"], ["s-a", "s-c"])).toEqual([
      "s-a",
    ]);
  });
});
