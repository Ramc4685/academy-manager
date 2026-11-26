import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import type { ReactNode } from "react";
import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it, vi } from "vitest";

import type { SkillNote } from "@/lib/api/coach";

vi.mock("@/components/ds/modal", () => ({
  Modal: ({ children }: { children: ReactNode }) => <div>{children}</div>,
}));
// The preview must never call a parent endpoint: the coach sees their own data.
const parentApi = vi.hoisted(() => ({ listParentChildSkillNotes: vi.fn() }));
vi.mock("@/lib/api/parent", () => parentApi);

import { CoachSkillNotesList } from "@/components/parent/coach-skill-notes";
import { SkillNotesPanel, parentPreviewNotes } from "./skill-notes-panel";

function note(id: string, visibility: "shared" | "private", shared_at: string | null): SkillNote {
  return {
    note_id: id,
    student_id: "st1",
    skill_id: "sk1",
    coach_id: "c1",
    session_id: null,
    body: `body ${id}`,
    created_at: "2026-11-01T10:00:00Z",
    visibility,
    shared_at,
  };
}

describe("SkillNotesPanel share control (S53)", () => {
  it("offers one Share with parent control and the parent preview", () => {
    const client = new QueryClient();
    client.setQueryData(["coach", "skill-notes", "st1", "sk1"], { notes: [] });
    const html = renderToStaticMarkup(
      <QueryClientProvider client={client}>
        <SkillNotesPanel open onClose={() => {}} studentId="st1" skillId="sk1" skillName="Grip" />
      </QueryClientProvider>,
    );
    expect(html).toContain("Share with parent");
    expect(html).toContain("Progress page");
    expect(html).toContain("See what the parent sees");
    expect(html).not.toContain("Mark as shared");
    expect(parentApi.listParentChildSkillNotes).not.toHaveBeenCalled();
  });

  it("previews only notes the parent will see, plus the shared draft", () => {
    const preview = parentPreviewNotes(
      [
        note("new", "shared", "2026-11-20T10:00:00Z"),
        note("legacy", "shared", null),
        note("mine", "private", null),
      ],
      "Grip",
      "Draft text",
    );
    expect(preview.map((n) => n.note_id)).toEqual(["draft", "new"]);
    const html = renderToStaticMarkup(<CoachSkillNotesList notes={preview} firstName="Alex" />);
    expect(html).toContain("body new");
    expect(html).toContain("Draft text");
    expect(html).not.toContain("body legacy");
    expect(html).not.toContain("body mine");
    expect(parentApi.listParentChildSkillNotes).not.toHaveBeenCalled();
  });
});
