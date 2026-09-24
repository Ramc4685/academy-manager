import { describe, expect, it } from "vitest";

import { formatAcceptedAt, formatFeeModel, hasAcceptedAgreement } from "./platform-agreement";

describe("platform agreement display", () => {
  it("labels the flat monthly fee model and passes unknown codes through", () => {
    expect(formatFeeModel("flat_monthly")).toBe("Flat monthly fee");
    expect(formatFeeModel("something_new")).toBe("something_new");
  });

  it("counts an acceptance only when all three fields are present", () => {
    const none = {
      platform_agreement_version: null,
      platform_agreement_accepted_at: null,
      platform_agreement_accepted_by: null,
    };
    expect(hasAcceptedAgreement(none)).toBe(false);
    expect(hasAcceptedAgreement({ ...none, platform_agreement_version: "v1" })).toBe(false);
    expect(
      hasAcceptedAgreement({
        platform_agreement_version: "v1",
        platform_agreement_accepted_at: "2026-10-01T12:00:00Z",
        platform_agreement_accepted_by: "owner@example.test",
      }),
    ).toBe(true);
    expect(
      hasAcceptedAgreement({
        platform_agreement_version: "  ",
        platform_agreement_accepted_at: "2026-10-01T12:00:00Z",
        platform_agreement_accepted_by: "owner@example.test",
      }),
    ).toBe(false);
  });

  it("formats the acceptance date in UTC and falls back to a dash", () => {
    expect(formatAcceptedAt("2026-10-01T23:30:00Z")).toBe("Oct 1, 2026");
    expect(formatAcceptedAt(null)).toBe("—");
    expect(formatAcceptedAt("not a date")).toBe("—");
  });
});
