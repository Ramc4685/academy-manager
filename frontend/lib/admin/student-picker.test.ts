import { describe, expect, it } from "vitest";

import { orderPickerResults, pinnedPickerOptions, studentPickerParams } from "./student-picker";

describe("studentPickerParams (L2 A0-2)", () => {
  it("browses a full server page when there is no search text", () => {
    expect(studentPickerParams("  ")).toEqual({ limit: 100 });
  });

  it("searches every student on the server when the admin types", () => {
    expect(studentPickerParams(" zoe ")).toEqual({ search: "zoe", limit: 100 });
  });
});

describe("orderPickerResults", () => {
  it("puts on-the-books students first and keeps name order otherwise", () => {
    const rows = [
      { name: "Aaron", lifecycle: "left" as const },
      { name: "Bea", lifecycle: "active" as const },
      { name: "Cal", lifecycle: "never_enrolled" as const },
      { name: "Dee", lifecycle: "paused" as const },
    ];
    expect(orderPickerResults(rows).map((r) => r.name)).toEqual(["Bea", "Dee", "Aaron", "Cal"]);
  });
});

describe("pinnedPickerOptions", () => {
  const zoe = { student_id: "s-zoe", full_name: "Zoe Example" };
  const amy = { student_id: "s-amy", full_name: "Amy Example" };

  it("keeps the picked student listed after a search drops them", () => {
    expect(pinnedPickerOptions([amy], "s-zoe", undefined, zoe)).toEqual([zoe]);
  });

  it("keeps a prefilled student and adds nothing already in the results", () => {
    expect(pinnedPickerOptions([amy], "s-amy", zoe, amy)).toEqual([zoe]);
  });

  it("drops a stale pick once the value moves on", () => {
    expect(pinnedPickerOptions([amy], "s-amy", undefined, zoe)).toEqual([]);
  });
});
