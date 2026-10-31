/**
 * Issue #843: the per-child avatar gradients must stay inside the Rally
 * palette (cobalt / slate / teal-green / amber-volt). The purple→pink stop
 * that shipped here was off-system — it is the one colour pair on the parent
 * Children list and kid-first Home cards that appears nowhere in
 * tailwind.config.ts.
 */
import { describe, expect, it } from "vitest";

import { nameGradient, nameInitial } from "./avatar-gradient";

/**
 * Every colour stop an avatar gradient is allowed to use. Cobalt and volt are
 * the Rally hues proper; the green/teal, cyan and amber pairs are the status
 * hues the design system already ships for chips. Purple and pink are not on
 * it.
 */
const ALLOWED_STOPS = new Set([
  "#2563eb", // rally.cobalt.600
  "#1d4ed8", // rally.cobalt.700
  "#1e3a8a", // rally.cobalt.900
  "#3b82f6", // rally.cobalt.500
  "#475569", // status.slate.600
  "#334155", // status.slate.700
  "#0f172a", // rally.ink
  "#059669",
  "#0d9488",
  "#0891b2",
  "#d97706",
  "#f59e0b", // status.amber.500
  "#facc15", // rally.volt.400
  "#a16207", // rally.volt.700
]);

function stopsOf(gradient: string): string[] {
  return gradient.match(/#[0-9a-f]{6}/gi)?.map((s) => s.toLowerCase()) ?? [];
}

// Enough names to cover every entry in the rotation.
const NAMES = Array.from({ length: 60 }, (_, i) => `Child Number ${i}`);

describe("nameGradient", () => {
  it("only uses Rally-system colour stops", () => {
    const offPalette = new Set<string>();
    for (const name of NAMES) {
      for (const stop of stopsOf(nameGradient(name))) {
        if (!ALLOWED_STOPS.has(stop)) offPalette.add(stop);
      }
    }
    expect([...offPalette]).toEqual([]);
  });

  it("never emits the off-system purple or pink stops", () => {
    const all = NAMES.map((n) => nameGradient(n)).join(" ").toLowerCase();
    expect(all).not.toContain("#7c3aed");
    expect(all).not.toContain("#db2777");
  });

  it("still gives the same child the same colour, and different children different ones", () => {
    expect(nameGradient("Ava Kim")).toBe(nameGradient("Ava Kim"));
    expect(new Set(NAMES.map((n) => nameGradient(n))).size).toBeGreaterThan(1);
  });
});

describe("nameInitial", () => {
  it("upper-cases the first letter and falls back to S", () => {
    expect(nameInitial("ava kim")).toBe("A");
    expect(nameInitial("   ")).toBe("S");
  });
});
