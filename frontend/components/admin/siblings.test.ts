import { createElement } from "react";
import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it } from "vitest";

import { SiblingsChip, siblingsOf } from "./siblings";

const children = [
  { student_id: "stu-a", name: "Ava", lifecycle: "active", lifecycle_as_of: null, classes: [], matched: false },
  { student_id: "stu-b", name: "Ben", lifecycle: "paused", lifecycle_as_of: null, classes: [], matched: false },
  { student_id: "stu-c", name: "Cleo", lifecycle: "left", lifecycle_as_of: null, classes: [], matched: false },
] as const;

const family = {
  family_id: "fam-1",
  children: [...children],
  sibling_student_ids: ["stu-a", "stu-b"],
};

describe("siblingsOf", () => {
  it("lists the enrolled children, or a student's enrolled siblings", () => {
    expect(siblingsOf(family).map((k) => k.name)).toEqual(["Ava", "Ben"]);
    expect(siblingsOf(family, "stu-a").map((k) => k.name)).toEqual(["Ben"]);
  });

  it("is empty for a child who left, one enrolled child, or an older payload", () => {
    expect(siblingsOf(family, "stu-c")).toEqual([]);
    expect(siblingsOf({ ...family, sibling_student_ids: [] })).toEqual([]);
    expect(siblingsOf({ ...family, sibling_student_ids: undefined })).toEqual([]);
  });
});

describe("SiblingsChip", () => {
  it("renders a count and names the children", () => {
    const html = renderToStaticMarkup(createElement(SiblingsChip, { family }));
    expect(html).toContain("Siblings · 2");
    expect(html).toContain('data-testid="family-siblings-fam-1"');
    expect(html).toContain("Enrolled children: Ava, Ben");
  });

  it("renders nothing for a family that is not a sibling family", () => {
    expect(renderToStaticMarkup(createElement(SiblingsChip, { family: { ...family, sibling_student_ids: [] } }))).toBe("");
  });
});
