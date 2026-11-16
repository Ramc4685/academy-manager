import { describe, expect, it, vi } from "vitest";

vi.mock("next/navigation", () => ({ useRouter: vi.fn() }));
vi.mock("@/lib/auth/firebase", () => ({ signOutCurrent: vi.fn() }));
vi.mock("@/lib/query/persistence", () => ({ clearPersistedQueryCache: vi.fn() }));
vi.mock("@/lib/offline/queue", () => ({
  clearAll: vi.fn(),
  list: vi.fn(async () => [
    { mutation_id: "a", status: "queued" },
    { mutation_id: "b", status: "in_flight" },
    { mutation_id: "c", status: "needs_review" },
  ]),
}));

import { unsentMarkCount } from "./logout-button";

describe("logout unsent-mark prompt", () => {
  it("counts Needs-review marks too, since sign-out clears them", async () => {
    expect(await unsentMarkCount()).toBe(3);
  });
});
