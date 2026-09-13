import { readFileSync, readdirSync } from "node:fs";
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
const DRAWER_SAFE_TOP = "pt-[calc(1rem+env(safe-area-inset-top,0px))]";
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

/**
 * Full-height overlays (`inset-y-0`) are top-anchored too: their header sits
 * under the status bar exactly like a shell header does. Enumerate them from
 * the source tree so a new one cannot ship without the same padding.
 */
const OVERLAY_SAFE_TOP = "env(safe-area-inset-top,0px)";

function tsxFiles(dir: string, acc: string[] = []): string[] {
  for (const entry of readdirSync(dir, { withFileTypes: true })) {
    const full = path.join(dir, entry.name);
    if (entry.isDirectory()) tsxFiles(full, acc);
    else if (entry.name.endsWith(".tsx")) acc.push(full);
  }
  return acc;
}

const topAnchoredOverlays = tsxFiles(APP)
  .filter((file) => readFileSync(file, "utf8").includes("inset-y-0"))
  .map((file) => path.relative(APP, file));

describe("top-anchored overlays pad for the iOS status bar", () => {
  it("correction drawer header carries the safe-area top padding", () => {
    const src = source("(admin)/admin/payouts/_components/CorrectionDrawer.tsx");
    expect(src).toContain(DRAWER_SAFE_TOP);
    // The inset must be added to the existing padding, not replace it.
    expect(src).not.toContain("border-b border-rally-line px-5 py-4");
  });

  it("finds every inset-y-0 overlay in app/", () => {
    // Guards the enumeration itself: an empty list would make the next test vacuous.
    expect(topAnchoredOverlays.length).toBeGreaterThan(0);
  });

  it.each(topAnchoredOverlays)("%s pads its top edge", (rel) => {
    expect(source(rel)).toContain(OVERLAY_SAFE_TOP);
  });
});
