import { describe, expect, it } from "vitest";

import {
  initialsComplete,
  initialsNeeded,
  parseWaiverSections,
  signingPathFor,
} from "./sections";

const BODY = `Intro paragraph.

## Risks [initials]
Badminton has risks.
## Adult release [adult]
I release the academy.
## Parent release [MINOR] [initials]
I release on behalf of my child.
`;

describe("waiver sections", () => {
  it("splits on headings and reads the tags, like the backend", () => {
    expect(parseWaiverSections(BODY).map((s) => [s.key, s.heading, s.initials, s.audience])).toEqual([
      ["s1", null, false, "all"],
      ["s2", "Risks", true, "all"],
      ["s3", "Adult release", false, "adult"],
      ["s4", "Parent release", true, "minor"],
    ]);
  });

  it("reads a plain body as one untitled section", () => {
    expect(parseWaiverSections("Plain text.")).toEqual([
      { key: "s1", heading: null, body: "Plain text.", initials: false, audience: "all" },
    ]);
  });

  it("asks for initials only on sections for the signers' paths", () => {
    const sections = parseWaiverSections(BODY);
    expect(initialsNeeded(sections, ["adult"])).toEqual(["s2"]);
    expect(initialsNeeded(sections, ["minor"])).toEqual(["s2", "s4"]);
    expect(initialsComplete(["s2"], { s2: "PP" })).toBe(true);
    expect(initialsComplete(["s2"], { s2: "P1" })).toBe(false);
  });

  it("turns adult on the 18th birthday", () => {
    expect(signingPathFor("2008-11-02", new Date("2026-11-01T12:00:00Z"))).toBe("minor");
    expect(signingPathFor("2008-11-02", new Date("2026-11-02T12:00:00Z"))).toBe("adult");
    expect(signingPathFor("", new Date())).toBeNull();
  });
});
