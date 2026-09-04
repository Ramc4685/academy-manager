import { readFileSync } from "node:fs";
import path from "node:path";
import { describe, expect, it } from "vitest";

/**
 * The installed PWA draws under the iOS status bar
 * (apple-mobile-web-app-status-bar-style=black-translucent + viewport-fit=cover).
 * Every sticky shell header must therefore pad by env(safe-area-inset-top),
 * or its buttons land in the status-bar zone where iOS swallows taps.
 * The layouts need auth to render, so this guards the source text instead.
 */
const HEADER_SAFE_TOP = "pt-[calc(0.75rem+env(safe-area-inset-top,0px))]";
const BARE_SAFE_TOP = "pt-[env(safe-area-inset-top,0px)]";
const TOAST_SAFE_BOTTOM = "bottom-[max(1rem,env(safe-area-inset-bottom,0px))]";

const APP = path.resolve(__dirname);

function source(rel: string): string {
  return readFileSync(path.join(APP, rel), "utf8");
}

describe("persona shell headers pad for the iOS status bar", () => {
  it.each(["(admin)", "(coach)", "(parent)", "(student)", "(platform)"])(
    "%s layout header carries the safe-area top padding",
    (group) => {
      const src = source(`${group}/layout.tsx`);
      expect(src).toContain(HEADER_SAFE_TOP);
      // The inset must be added to the existing padding, not replace it.
      expect(src).not.toMatch(/<header[^>]*className="[^"]*\bpy-3\b/);
    },
  );

  it("admin mobile drawer pads its top edge", () => {
    expect(source("(admin)/layout.tsx")).toContain(BARE_SAFE_TOP);
  });

  it("toast stack clears the home indicator", () => {
    expect(source("../components/ds/toast.tsx")).toContain(TOAST_SAFE_BOTTOM);
    expect(source("../components/ds/toast.tsx")).not.toContain(" bottom-4 ");
  });
});
