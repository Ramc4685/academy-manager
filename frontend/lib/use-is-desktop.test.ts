import { describe, expect, it } from "vitest";

import { DESKTOP_QUERY } from "./use-is-desktop";

describe("DESKTOP_QUERY", () => {
  it("matches Tailwind's lg breakpoint in the same unit (64rem, not px)", () => {
    // Tailwind 4's `lg:` is 64rem. A px query only agrees at a 16px root
    // font size; at a larger user font size the sidebar tree would mount
    // while its `lg:` classes stay inactive, leaving no navigation at all.
    expect(DESKTOP_QUERY).toBe("(min-width: 64rem)");
    expect(DESKTOP_QUERY).not.toMatch(/px/);
  });
});
