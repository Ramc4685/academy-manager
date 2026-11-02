import { createElement } from "react";
import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it } from "vitest";

import { WaiverSignBlock } from "./waiver-sign-block";

// Fictional fixture: no real family.
function render(children: { student_id: string; student_name: string }[]): string {
  return renderToStaticMarkup(
    createElement(WaiverSignBlock, {
      childrenToSign: children,
      consentText: "I agree to sign electronically.",
      busy: false,
      error: null,
      label: (chosen) => `Sign waiver for ${chosen.length}`,
      onSign: () => {},
    }),
  );
}

describe("WaiverSignBlock", () => {
  it("starts with Sign disabled and the consent box unticked", () => {
    const html = render([{ student_id: "st-1", student_name: "Kid One" }]);
    expect(html).toMatch(/<button[^>]*disabled/);
    expect(html).toContain("I agree to sign electronically.");
    expect(html).not.toMatch(/type="checkbox"[^>]*checked/);
  });

  it("asks for a full legal name", () => {
    expect(render([])).toContain("Full legal name");
  });

  it("offers a choice of children only when there is more than one", () => {
    expect(render([{ student_id: "st-1", student_name: "Kid One" }])).not.toContain("Sign for");
    const html = render([
      { student_id: "st-1", student_name: "Kid One" },
      { student_id: "st-2", student_name: "Kid Two" },
    ]);
    expect(html).toContain("Sign for");
    expect(html).toContain("Kid Two");
    expect(html).toContain("Sign waiver for 2");
  });
});
