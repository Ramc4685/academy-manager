import { describe, expect, it } from "vitest";

import { overflowEdges } from "./overflow-cue";

describe("overflowEdges", () => {
  it("reports nothing when the strip fits", () => {
    expect(overflowEdges({ scrollLeft: 0, clientWidth: 400, scrollWidth: 400 })).toEqual({
      left: false,
      right: false,
    });
  });

  it("shows the right cue at the start of an overflowing strip", () => {
    expect(overflowEdges({ scrollLeft: 0, clientWidth: 400, scrollWidth: 900 })).toEqual({
      left: false,
      right: true,
    });
  });

  it("shows both cues mid-scroll and only the left one at the end", () => {
    expect(overflowEdges({ scrollLeft: 200, clientWidth: 400, scrollWidth: 900 })).toEqual({
      left: true,
      right: true,
    });
    expect(overflowEdges({ scrollLeft: 500, clientWidth: 400, scrollWidth: 900 })).toEqual({
      left: true,
      right: false,
    });
  });

  it("ignores sub-pixel slack", () => {
    expect(overflowEdges({ scrollLeft: 0.5, clientWidth: 400, scrollWidth: 400.6 })).toEqual({
      left: false,
      right: false,
    });
  });
});
