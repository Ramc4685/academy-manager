import { describe, expect, it, vi } from "vitest";

const result = vi.hoisted(() => ({
  current: { kind: "not_found" } as unknown,
}));
vi.mock("@/lib/public-page/shared-certificate", () => ({
  loadSharedCertificate: async () => result.current,
  formatIssuedOn: (value: string) => value,
}));

import { generateMetadata } from "./page";

const params = Promise.resolve({ token: "A".repeat(22) });

describe("/c/[token] metadata", () => {
  it("is never indexed, even for a live share (a child's record)", async () => {
    result.current = {
      kind: "found",
      certificate: {
        academy: {
          name: "Riverside",
          logo_url: null,
          brand_color: null,
          brand_fill: "#000",
          brand_on_color: "#fff",
        },
        recipient_name: "Maya",
        level_name: "Grip",
        level_number: 1,
        level_color: null,
        cert_number: "RIV-C-0001",
        issued_on: "2026-10-30",
      },
    };
    expect((await generateMetadata({ params })).robots).toEqual({
      index: false,
      follow: false,
    });
  });

  it("is noindex for a revoked or unknown link", async () => {
    result.current = { kind: "not_found" };
    expect((await generateMetadata({ params })).robots).toEqual({
      index: false,
      follow: false,
    });
  });
});
