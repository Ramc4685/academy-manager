import { describe, expect, it } from "vitest";

import { orderPickerResults, studentPickerParams } from "./student-picker";

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
