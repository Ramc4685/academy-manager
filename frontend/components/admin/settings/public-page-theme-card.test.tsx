import { renderToStaticMarkup } from "react-dom/server";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { describe, expect, it, vi } from "vitest";

vi.mock("@/lib/api/admin", () => ({ getAdminAcademy: vi.fn() }));

import { queryKeys } from "@/lib/query/keys";
import { PublicPageThemeCard } from "./public-page-theme-card";

function html(academy: Record<string, unknown>, value: "floodlit" | "daylight" | "showcase") {
  const client = new QueryClient();
  client.setQueryData(queryKeys.admin.academy(), academy);
  return renderToStaticMarkup(
    <QueryClientProvider client={client}>
      <PublicPageThemeCard value={value} onChange={() => {}} />
    </QueryClientProvider>,
  );
}

describe("PublicPageThemeCard", () => {
  const academy = {
    display_name: "Lakeside Racquet Academy",
    brand_color: "#facc15",
    logo_url: "https://cdn.example.test/logo.png",
  };

  it("offers the three presets and marks the chosen one", () => {
    const out = html(academy, "daylight");
    for (const theme of ["floodlit", "daylight", "showcase"]) {
      expect(out).toContain(`data-testid="public-page-theme-${theme}"`);
    }
    expect(out).toMatch(/checked="" value="daylight"/);
    expect(out).not.toMatch(/checked="" value="floodlit"/);
    expect(out).toContain("adjusted so text is always readable");
  });

  it("previews the academy's own logo and brand colour", () => {
    const out = html(academy, "floodlit");
    expect(out).toContain('src="https://cdn.example.test/logo.png"');
    expect(out).toContain("background:#facc15");
    expect(out).toContain("Lakeside Racquet Academy");
  });

  it("falls back to a monogram when there is no logo", () => {
    const out = html({ ...academy, logo_url: null }, "floodlit");
    expect(out).not.toContain("<img");
    expect(out).toContain(">LR<");
  });
});
