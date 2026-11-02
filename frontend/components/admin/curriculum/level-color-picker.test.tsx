import { renderToStaticMarkup } from "react-dom/server";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { describe, expect, it, vi } from "vitest";

vi.mock("@/lib/api/curriculum", () => ({ setLevelColor: vi.fn() }));

import type { Level } from "@/lib/api/curriculum";
import { levelColorName, levelSwatch } from "@/lib/level-color";
import { LevelColorPicker } from "./level-color-picker";

function html(level: Partial<Level>) {
  return renderToStaticMarkup(
    <QueryClientProvider client={new QueryClient()}>
      <LevelColorPicker
        level={{ level_id: "l2", sequence: 2, color: null, display_color: "#FB923C", ...level } as Level}
        onSaved={() => {}}
      />
    </QueryClientProvider>,
  );
}

describe("LevelColorPicker", () => {
  it("marks the current preset and hides reset while on the default", () => {
    const out = html({});
    expect(out).toContain("Level 2 · Orange");
    expect(out).toContain('aria-label="Orange" aria-pressed="true"');
    expect(out).not.toContain("Use default");
  });

  it("offers reset once the owner picked a custom colour", () => {
    const out = html({ color: "#0EA5E9", display_color: "#0EA5E9" });
    expect(out).toContain("Level 2 · Custom");
    expect(out).toContain("Use default");
  });
});

describe("level colour helpers", () => {
  it("names presets and falls back on bad input", () => {
    expect(levelColorName("#fde047")).toBe("Yellow");
    expect(levelColorName("#123456")).toBeNull();
    expect(levelSwatch("not-a-colour")).toEqual(levelSwatch("#2563EB"));
    expect(levelSwatch("#111827").on).toBe("#ffffff");
    expect(levelSwatch("#FDE047")).toEqual({ fill: "#FDE047", on: "#000000" });
  });
});
