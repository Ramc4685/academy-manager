import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it, vi } from "vitest";

vi.mock("@tanstack/react-query", () => ({ useQueryClient: () => ({ clear: vi.fn() }) }));
vi.mock("@/lib/auth/firebase", () => ({
  reauthMethods: () => [],
  reauthenticate: vi.fn(),
  signOutCurrent: vi.fn(),
}));
vi.mock("@/lib/api/me", () => ({ requestAccountDeletion: vi.fn() }));
vi.mock("@/lib/query/persistence", () => ({ clearPersistedQueryCache: vi.fn() }));

import { DeleteAccountSection } from "./delete-account-section";

describe("DeleteAccountSection disclosure (S19)", () => {
  it("sits closed behind a neutral Account summary", () => {
    const html = renderToStaticMarkup(<DeleteAccountSection persona="coach" />);
    expect(html).toMatch(/^<details[^>]*data-testid="account-disclosure"/);
    expect(html).not.toMatch(/<details[^>]*\sopen/);
    const summary = html.match(/<summary[^>]*>(.*?)<\/summary>/)?.[1];
    expect(summary).toBe("Account");
    // The delete control is inside the disclosure, not before it.
    expect(html.indexOf("delete-account-open")).toBeGreaterThan(html.indexOf("</summary>"));
  });
});
