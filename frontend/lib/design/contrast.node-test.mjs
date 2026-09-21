/**
 * A11y guards for #844 — coach/admin contrast failures and the colour-only
 * skill board.
 *
 * Two kinds of assertion:
 *  1. Colour maths — the tokens we swap *to* clear WCAG AA (4.5:1), and the
 *     raw Tailwind greys/hexes we swapped *away from* provably do not. This
 *     pins the reasoning so a future "just use green-600, it looks fine"
 *     cannot quietly regress the surfaces.
 *  2. Source guards — the specific files named in the issue no longer carry
 *     the failing classes/hexes, and the skill board encodes status with a
 *     glyph + legend rather than colour alone (WCAG 1.4.1).
 */

import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { dirname, join } from "node:path";
import test from "node:test";
import { fileURLToPath } from "node:url";

import { AA_TEXT, contrastRatio } from "./contrast.mjs";

const FRONTEND = join(dirname(fileURLToPath(import.meta.url)), "..", "..");
const read = (relative) => readFileSync(join(FRONTEND, relative), "utf8");

// Surfaces the failing text sits on.
const WHITE = "#ffffff";
const NIGHT = "#0a0f1c"; // rally.night — the coach bottom nav
const GREEN_50 = "#ecfdf5"; // status.green.50
const GREEN_800 = "#065f46"; // status.green.800
const RED_800 = "#991b1b"; // status.red.800
const MUTED = "#64748b"; // rally.muted / rally.subtle
const SUBTLE_INK = "#94a3b8"; // rally.subtle-ink — night surfaces only

test("contrast helper matches the WCAG reference values", () => {
  assert.equal(Math.round(contrastRatio("#ffffff", "#000000")), 21);
  assert.equal(Math.round(contrastRatio("#ffffff", "#ffffff")), 1);
  // Order must not matter.
  assert.equal(contrastRatio(WHITE, MUTED), contrastRatio(MUTED, WHITE));
});

test("the colours #844 removes really do fail AA", () => {
  // Coach day-group heading / passport skill descriptions: text-neutral-400.
  assert.ok(contrastRatio(WHITE, "#a3a3a3") < AA_TEXT);
  // White on Tailwind green-600 — "Present" / "Mark all present".
  assert.ok(contrastRatio(WHITE, "#16a34a") < AA_TEXT);
  // Required-skill asterisk: text-red-500.
  assert.ok(contrastRatio(WHITE, "#ef4444") < AA_TEXT);
  // Inactive bottom-nav label: rally.muted on the night nav.
  assert.ok(contrastRatio(NIGHT, MUTED) < AA_TEXT);
});

test("the tokens #844 swaps in clear AA on their own surfaces", () => {
  assert.ok(contrastRatio(WHITE, MUTED) >= AA_TEXT, "muted on white");
  assert.ok(contrastRatio("#f8fafc", MUTED) >= AA_TEXT, "muted on paper");
  assert.ok(contrastRatio(NIGHT, SUBTLE_INK) >= AA_TEXT, "subtle-ink on night");
  assert.ok(contrastRatio(WHITE, GREEN_800) >= AA_TEXT, "green-800 fill on white text");
  assert.ok(contrastRatio(GREEN_50, GREEN_800) >= AA_TEXT, "green-800 on green-50");
  assert.ok(contrastRatio(WHITE, RED_800) >= AA_TEXT, "red-800 asterisk on white");
  // The already-passing Absent pair must be left alone, not "fixed".
  assert.ok(contrastRatio(WHITE, "#dc2626") >= AA_TEXT, "red-600 fill on white text");
});

test("coach session list heading no longer uses text-neutral-400", () => {
  assert.ok(!read("app/(coach)/coach/sessions/page.tsx").includes("text-neutral-400"));
});

test("coach passport descriptions no longer use text-neutral-400", () => {
  assert.ok(
    !read("app/(coach)/coach/students/[studentId]/passport/page.tsx").includes(
      "text-neutral-400",
    ),
  );
});

test("admin student progress uses DS tokens, not raw neutrals", () => {
  const source = read("app/(admin)/admin/students/[studentId]/progress/page.tsx");
  assert.ok(!source.includes("text-neutral-400"));
  assert.ok(!source.includes("text-neutral-500"));
});

test("coach attendance marks use the AA green and a visible unselected outline", () => {
  const source = read("app/(coach)/coach/sessions/[id]/page.tsx");
  assert.ok(!source.includes("#16a34a"), "selected Present drops Tailwind green-600");
  assert.ok(!source.includes("bg-green-600"), "Mark all present drops Tailwind green-600");
  assert.ok(source.includes(GREEN_800), "selected Present uses status-green-800");
  // Unselected Present/Absent: a 1px --rally-line hairline vanished in glare.
  const base = source.match(/const MARK_BUTTON_BASE\s*=\s*\n?\s*"([^"]*)"/);
  assert.ok(base, "MARK_BUTTON_BASE is a single string literal");
  assert.ok(base[1].includes("border-2"), "unselected mark buttons have a 2px border");
  assert.ok(!/\bborder\b(?!-)/.test(base[1]), "…and not the old 1px border");
  // Both unselected branches (Present, Absent) outline with the muted token.
  const outlined = source.match(/borderColor: "var\(--rally-muted\)"/g) ?? [];
  assert.equal(outlined.length, 2, "Present and Absent both use the muted outline");
});

test("coach bottom nav inactive label uses the night-surface token", () => {
  const source = read("app/(coach)/layout.tsx");
  const inactive = source.match(/color: active \? "#[0-9a-f]{6}" : "(#[0-9a-f]{6})"/);
  assert.ok(inactive, "BottomTab still sets an active/inactive colour pair");
  assert.equal(inactive[1], SUBTLE_INK, "inactive tab uses rally.subtle-ink, not rally.muted");
  assert.notEqual(inactive[1], MUTED);
});

test("skill board is readable without colour", () => {
  const source = read("components/pathway/skill-board.tsx");
  assert.ok(!source.includes("text-red-500"), "required asterisk uses status-red-800");
  assert.ok(source.includes("STATUS_GLYPH"), "each status carries a non-colour glyph");
  assert.ok(source.includes("skill-board-legend"), "the board renders a status legend");
  // Every status needs a glyph, not just the obvious ones.
  const glyphBlock = source.slice(
    source.indexOf("const STATUS_GLYPH"),
    source.indexOf("};", source.indexOf("const STATUS_GLYPH")),
  );
  for (const status of [
    "NOT_STARTED",
    "INTRODUCED",
    "LEARNING",
    "PRACTICING",
    "TEST_READY",
    "PASSED",
    "NEEDS_REVIEW",
  ]) {
    assert.ok(glyphBlock.includes(status), `${status} has a glyph`);
  }
});
