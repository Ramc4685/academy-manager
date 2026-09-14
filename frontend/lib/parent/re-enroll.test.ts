import { describe, expect, it } from "vitest";

import { RE_ENROLL_CHILD_PARAM, reEnrollChildId, reEnrollHref } from "./re-enroll";

describe("reEnrollHref (#827)", () => {
  it("sends the family into onboarding with the departed child pre-bound", () => {
    expect(reEnrollHref("st-1")).toBe("/parent/onboarding?child=st-1");
  });

  it("escapes an id that would otherwise break out of the query string", () => {
    expect(reEnrollHref("st/1&role=admin")).toBe(
      "/parent/onboarding?child=st%2F1%26role%3Dadmin",
    );
  });

  it("names the parameter the onboarding stepper reads back", () => {
    expect(RE_ENROLL_CHILD_PARAM).toBe("child");
  });
});

describe("reEnrollChildId (#827)", () => {
  it("reads the pre-bound child back out of the onboarding url", () => {
    const href = reEnrollHref("st-1");
    expect(reEnrollChildId(href.slice(href.indexOf("?")))).toBe("st-1");
  });

  it("round-trips an id that needed escaping", () => {
    const href = reEnrollHref("st/1&role=admin");
    expect(reEnrollChildId(href.slice(href.indexOf("?")))).toBe("st/1&role=admin");
  });

  it("is null for a plain onboarding visit, so first-time signup is untouched", () => {
    expect(reEnrollChildId("")).toBeNull();
    expect(reEnrollChildId("?step=child")).toBeNull();
    expect(reEnrollChildId("?child=")).toBeNull();
  });
});
