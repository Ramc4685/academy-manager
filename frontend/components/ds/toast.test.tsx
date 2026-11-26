import { createElement } from "react";
import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it } from "vitest";

import { ToastCard } from "./toast";

describe("ToastCard", () => {
  it("renders an action button next to the message", () => {
    const html = renderToStaticMarkup(
      createElement(ToastCard, {
        item: {
          id: "t1",
          kind: "success",
          title: "Student removed",
          action: { label: "Undo", onClick: () => undefined },
        },
        onDismiss: () => undefined,
      }),
    );
    expect(html).toContain("Student removed");
    expect(html).toMatch(/<button type="button"[^>]*>Undo<\/button>/);
  });

  it("renders no action button without an action", () => {
    const html = renderToStaticMarkup(
      createElement(ToastCard, {
        item: { id: "t2", kind: "info", title: "Saved" },
        onDismiss: () => undefined,
      }),
    );
    expect(html).not.toContain("Undo");
  });
});
