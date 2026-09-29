import { renderToStaticMarkup } from "react-dom/server";
import { beforeEach, describe, expect, it, vi } from "vitest";

let search = "panel=curriculum";

vi.mock("next/navigation", () => ({
  usePathname: () => "/admin/settings",
  useRouter: () => ({ push: vi.fn() }),
  useSearchParams: () => new URLSearchParams(search),
}));
vi.mock("@/components/admin/curriculum/program-list", () => ({
  ProgramList: () => <div>program-list</div>,
}));
vi.mock("@/components/admin/curriculum/program-editor", () => ({
  ProgramEditor: ({ programId }: { programId: string }) => <div>editor {programId}</div>,
}));

import { CurriculumPanel } from "./curriculum-panel";

describe("CurriculumPanel", () => {
  beforeEach(() => {
    search = "panel=curriculum";
  });

  it("shows the program list without a program param", () => {
    const html = renderToStaticMarkup(<CurriculumPanel />);
    expect(html).toContain("program-list");
    expect(html).not.toContain("editor");
  });

  it("opens the editor for ?program=<id>", () => {
    search = "panel=curriculum&program=prog_1";
    const html = renderToStaticMarkup(<CurriculumPanel />);
    expect(html).toContain("editor prog_1");
    expect(html).not.toContain("program-list");
  });
});
