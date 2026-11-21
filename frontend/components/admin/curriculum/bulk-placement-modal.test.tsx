import type { ReactNode } from "react";
import { renderToStaticMarkup } from "react-dom/server";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { describe, expect, it, vi } from "vitest";

vi.mock("@/lib/api/curriculum", () => ({ getFullPathway: vi.fn(), placeStudentsInBulk: vi.fn() }));
// The real Modal portals into document.body; render it inline for static markup.
vi.mock("@/components/ds/modal", () => ({
  Modal: ({ title, children }: { title: string; children: ReactNode }) => (
    <div>
      <h2>{title}</h2>
      {children}
    </div>
  ),
}));

import { BulkPlacementModal } from "./bulk-placement-modal";

describe("BulkPlacementModal", () => {
  it("counts only the selected students still on screen after a filter change", () => {
    // s1 and s2 were picked under "All actions"; the new filter shows s2 and s3.
    const out = renderToStaticMarkup(
      <QueryClientProvider client={new QueryClient()}>
        <BulkPlacementModal
          open
          programId="prog-1"
          studentIds={["s1", "s2"]}
          visibleIds={["s2", "s3"]}
          onClose={() => {}}
          onPlaced={() => {}}
        />
      </QueryClientProvider>,
    );
    expect(out).toContain("Place 1 student<");
  });
});
