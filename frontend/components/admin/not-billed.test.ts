import { describe, expect, it } from "vitest";

import { headcountLabel, notBilledReasonText, notBilledSuffix } from "./not-billed";

describe("not billed wording", () => {
  it("names the reason, or the note for Other", () => {
    expect(notBilledReasonText("coach_child")).toBe("Coach's child");
    expect(notBilledReasonText("other", "Volunteer's son")).toBe("Volunteer's son");
    expect(notBilledReasonText(null)).toBeNull();
  });

  it("adds +N only when there are any", () => {
    expect(notBilledSuffix(2)).toBe(" · +2 not billed");
    expect(notBilledSuffix(0)).toBe("");
    expect(notBilledSuffix(undefined)).toBe("");
  });

  it("labels paying against enrolled the same way everywhere", () => {
    expect(headcountLabel(9, 11)).toBe("9 paying of 11 enrolled");
    expect(headcountLabel(11, 11)).toBe("11 enrolled");
  });
});
