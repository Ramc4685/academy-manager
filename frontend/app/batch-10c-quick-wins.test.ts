import { readFileSync } from "node:fs";
import { join } from "node:path";
import { describe, expect, it } from "vitest";

// Source-level guards for four verified findings of the 2026-09-21 critique
// (run 3). Same style as failed-loads-not-all-clear.test.ts: each asserts the
// wiring that a rendered test would otherwise need a full page stub for.
const root = join(__dirname, "..");
const read = (rel: string) => readFileSync(join(root, rel), "utf8");

describe("batch-10c quick wins", () => {
  it("rally-cobalt has a DEFAULT shade, so bare `rally-cobalt` classes emit CSS", () => {
    const config = read("tailwind.config.ts");
    const cobalt = config.slice(config.indexOf("cobalt: {"), config.indexOf("volt: {"));
    expect(cobalt).toMatch(/DEFAULT:\s*"#2563eb"/);
  });

  it("parent bottom-nav inactive labels meet AA on the night bar", () => {
    const layout = read("app/(parent)/layout.tsx");
    expect(layout).not.toContain('"#475569"');
    expect(layout).toContain('active ? "#facc15" : "#94a3b8"');
  });

  it("a failed admin direct-message send is visible, not screen-reader only", () => {
    const page = read("app/(admin)/admin/messages/page.tsx");
    expect(page).not.toMatch(/role="alert" className="sr-only">\{error\}/);
    expect(page).toMatch(/role="alert" className="basis-full[^"]*text-status-red-800"/);
  });

  it("Disconnect Stripe asks for confirmation before calling the API", () => {
    const panel = read("components/admin/settings/gateway-panel.tsx");
    expect(panel).toContain("ConfirmActionDialog");
    expect(panel).toContain("onClick={() => setConfirmDisconnect(true)}");
    expect(panel).not.toContain("onClick={() => disconnectMutation.mutate()}");
    expect(panel).toContain("onConfirm={() => disconnectMutation.mutate()}");
  });
});
