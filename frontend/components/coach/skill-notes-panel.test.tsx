import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import type { ReactNode } from "react";
import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it, vi } from "vitest";

vi.mock("@/components/ds/modal", () => ({
  Modal: ({ children }: { children: ReactNode }) => <div>{children}</div>,
}));

import { SkillNotesPanel } from "./skill-notes-panel";

describe("SkillNotesPanel share control", () => {
  it("says plainly that parents do not see skill notes today", () => {
    const client = new QueryClient();
    client.setQueryData(["coach", "skill-notes", "st1", "sk1"], { notes: [] });
    const html = renderToStaticMarkup(
      <QueryClientProvider client={client}>
        <SkillNotesPanel open onClose={() => {}} studentId="st1" skillId="sk1" skillName="Grip" />
      </QueryClientProvider>,
    );
    expect(html).toContain("Mark as shared");
    expect(html).toContain("Today parents do not see skill notes, shared or not.");
    expect(html).not.toContain("parent portal yet");
  });
});
