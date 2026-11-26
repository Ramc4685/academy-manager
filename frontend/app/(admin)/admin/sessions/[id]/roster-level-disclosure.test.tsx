import { readFileSync } from "node:fs";
import path from "node:path";
import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it } from "vitest";

import type { Level } from "@/lib/api/curriculum";

import { LevelSelect } from "./RosterPanel";

const LEVELS = [
  { level_id: "l1", sequence: 1, name: "Foundations" },
  { level_id: "l2", sequence: 2, name: "Rally" },
] as Level[];

describe("roster level picker (S29)", () => {
  it("shows the level as text with the dropdown behind a closed disclosure", () => {
    const html = renderToStaticMarkup(
      <LevelSelect value="l2" levels={LEVELS} disabled={false} onChange={() => {}} />,
    );
    expect(html).toMatch(/^<details/);
    expect(html).not.toContain("<details open");
    expect(html).toContain("L2 · Rally");
    expect(html).toContain("Change level");
    expect(html.indexOf("<select")).toBeGreaterThan(html.indexOf("</summary>"));
  });

  it("says Not placed for a student with no level", () => {
    const html = renderToStaticMarkup(
      <LevelSelect value="" levels={LEVELS} disabled={false} onChange={() => {}} />,
    );
    expect(html).toContain("Not placed");
  });
});

describe("Payment system status is reachable from Integrations (S29)", () => {
  it("links the demoted Billing Health page from the Integrations panel", () => {
    const src = readFileSync(
      path.resolve(__dirname, "../../../../../components/admin/settings/gateway-panel.tsx"),
      "utf8",
    );
    expect(src).toContain('href="/admin/billing-health"');
    expect(src).toContain("Payment system status");
  });
});
