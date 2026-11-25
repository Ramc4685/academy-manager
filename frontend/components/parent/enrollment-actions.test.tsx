import { createElement } from "react";
import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it, vi } from "vitest";

import { EnrollmentActions, enrollmentActionItems } from "./enrollment-actions";

const noop = () => {};

function render(overrides: { canRequestPause?: boolean; canRequestCancel?: boolean } = {}) {
  return renderToStaticMarkup(
    createElement(EnrollmentActions, {
      enrollmentId: "enr-1",
      sessionTitle: "Junior Beginners",
      childName: "Alex Rivera",
      canRequestPause: true,
      canRequestCancel: true,
      pausing: false,
      onPause: noop,
      onCancel: noop,
      ...overrides,
    }),
  );
}

describe("EnrollmentActions", () => {
  it("gives phones one Manage enrollment menu and keeps inline buttons for wider screens", () => {
    const html = render();
    // Phone branch: a single trigger naming the child and the class.
    expect(html).toContain('data-testid="enrollment-manage-enr-1"');
    expect(html).toContain("Manage enrollment");
    // Accessible name keeps the visible phrase (WCAG 2.5.3 label in name).
    expect(html).toContain('aria-label="Manage enrollment for Alex Rivera in Junior Beginners"');
    expect(html).toMatch(/class="sm:hidden"/);
    // Wider screens: the inline buttons, hidden below sm.
    expect(html).toMatch(/class="hidden shrink-0 items-center gap-2 sm:flex"/);
    expect(html).toContain("Pause enrollment");
    expect(html).toContain("Cancel enrollment…");
  });

  it("renders nothing when the academy has switched both actions off", () => {
    expect(render({ canRequestPause: false, canRequestCancel: false })).toBe("");
  });
});

describe("enrollmentActionItems", () => {
  it("offers only the actions the academy allows, wired to the same handlers", () => {
    const onPause = vi.fn();
    const onCancel = vi.fn();

    const both = enrollmentActionItems({ canRequestPause: true, canRequestCancel: true, onPause, onCancel });
    expect(both.map((i) => i.label)).toEqual(["Pause enrollment", "Cancel enrollment…"]);
    expect(both[1].danger).toBe(true);
    both[0].onSelect?.();
    both[1].onSelect?.();
    expect(onPause).toHaveBeenCalledOnce();
    expect(onCancel).toHaveBeenCalledOnce();

    expect(
      enrollmentActionItems({ canRequestPause: false, canRequestCancel: true, onPause, onCancel }).map(
        (i) => i.key,
      ),
    ).toEqual(["cancel"]);
  });
});
