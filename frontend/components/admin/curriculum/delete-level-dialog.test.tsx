import { Children, isValidElement, type ReactElement, type ReactNode } from "react";
import { renderToStaticMarkup } from "react-dom/server";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { beforeEach, describe, expect, it, vi } from "vitest";

const modal = vi.hoisted(() => ({ footer: null as ReactNode }));

vi.mock("@/lib/api/curriculum", () => ({ deleteLevel: vi.fn() }));
// The real Modal portals into document.body, which a node render has no DOM for.
vi.mock("@/components/ds/modal", () => ({
  Modal: ({ open, title, children, footer }: { open: boolean; title: ReactNode; children: ReactNode; footer: ReactNode }) => {
    modal.footer = footer;
    return open ? (
      <div role="dialog">
        <h2>{title}</h2>
        {children}
        {footer}
      </div>
    ) : null;
  },
}));

import { deleteLevel, type PathwayLevel } from "@/lib/api/curriculum";
import { DeleteLevelDialog } from "./delete-level-dialog";

const pathwayLevel = {
  level: { level_id: "lv-7", sequence: 7, name: "Smash Lab" },
  skills: [
    { skill: { skill_id: "s1" }, criteria: [{}, {}], external_refs: [] },
    { skill: { skill_id: "s2" }, criteria: [{}], external_refs: [] },
  ],
} as unknown as PathwayLevel;

function render(open: boolean, handlers = { onClose: vi.fn(), onDeleted: vi.fn() }) {
  const html = renderToStaticMarkup(
    <QueryClientProvider client={new QueryClient()}>
      <DeleteLevelDialog pathwayLevel={pathwayLevel} open={open} {...handlers} />
    </QueryClientProvider>,
  );
  return { html, ...handlers };
}

function confirmButton(): ReactElement<{ onClick: () => void }> {
  const button = Children.toArray(
    (modal.footer as ReactElement<{ children: ReactNode }>).props.children,
  ).find(
    (child) =>
      isValidElement<{ "data-testid"?: string }>(child) &&
      child.props["data-testid"] === "confirm-delete-level",
  );
  return button as ReactElement<{ onClick: () => void }>;
}

describe("DeleteLevelDialog", () => {
  beforeEach(() => vi.mocked(deleteLevel).mockReset());

  it("renders nothing until opened", () => {
    expect(render(false).html).toBe("");
  });

  it("names the level and what goes with it before confirming", () => {
    const { html } = render(true);
    expect(html).toContain("Delete level 7: Smash Lab?");
    expect(html).toContain("its 2 skills and 3 criteria");
    expect(html).toContain("cannot be undone");
    expect(html).toContain("Delete level</button>");
    expect(deleteLevel).not.toHaveBeenCalled();
  });

  it("deletes on confirm, then refreshes and closes", async () => {
    vi.mocked(deleteLevel).mockResolvedValue({
      level_id: "lv-7",
      deleted: { levels: 1, skills: 2, criteria: 3 },
    });
    const { onClose, onDeleted } = render(true);

    confirmButton().props.onClick();

    await vi.waitFor(() => expect(onClose).toHaveBeenCalled());
    expect(deleteLevel).toHaveBeenCalledWith("lv-7");
    expect(onDeleted).toHaveBeenCalled();
  });
});
