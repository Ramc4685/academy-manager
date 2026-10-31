import { readdirSync, readFileSync, statSync } from "node:fs";
import path from "node:path";
import type { ReactElement } from "react";
import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it, vi } from "vitest";

import { RETRY_BUTTON_CLASSES, RetryButton } from "./RetryButton";

type ButtonProps = {
  type?: string;
  onClick?: () => void;
  disabled?: boolean;
  children?: unknown;
  className?: string;
};

function element(props: Parameters<typeof RetryButton>[0]): ReactElement<ButtonProps> {
  return RetryButton(props) as ReactElement<ButtonProps>;
}

describe("RetryButton", () => {
  it("is a native button whose accessible name is Retry", () => {
    const html = renderToStaticMarkup(<RetryButton onClick={() => {}} />);
    // A <button> element carries the implicit role=button; its text is its name.
    expect(html).toMatch(/^<button type="button"[^>]*>Retry<\/button>$/);
    expect(html).not.toContain('disabled=""');
  });

  it("fires onClick", () => {
    const onClick = vi.fn();
    const el = element({ onClick });
    expect(el.type).toBe("button");
    el.props.onClick?.();
    expect(onClick).toHaveBeenCalledTimes(1);
  });

  it("shows Retrying… while busy and honours disabled", () => {
    const html = renderToStaticMarkup(<RetryButton onClick={() => {}} busy disabled testId="r1" />);
    expect(html).toContain(">Retrying…</button>");
    expect(html).toContain('disabled=""');
    expect(html).toContain('data-testid="r1"');
  });

  it("paints AA-safe defined tokens and keeps caller classes to layout", () => {
    // White on rally-cobalt-700 is 6.70:1. The old tray button was white on
    // amber-600 (3.2:1). No undefined rally-accent classes.
    expect(RETRY_BUTTON_CLASSES).toContain("bg-rally-cobalt-700");
    expect(RETRY_BUTTON_CLASSES).toContain("text-white");
    expect(RETRY_BUTTON_CLASSES).toContain("focus-visible:outline-rally-cobalt-700");
    expect(RETRY_BUTTON_CLASSES).toContain("dark:focus-visible:outline-rally-cobalt-500");
    expect(RETRY_BUTTON_CLASSES).not.toMatch(/rally-accent|amber/);
    const el = element({ onClick: () => {}, className: "mt-2" });
    expect(el.props.className?.endsWith(" mt-2")).toBe(true);
  });
});

function walk(dir: string): string[] {
  return readdirSync(dir).flatMap((name) => {
    const full = path.join(dir, name);
    return statSync(full).isDirectory() ? walk(full) : full.endsWith(".tsx") ? [full] : [];
  });
}

describe("coach screens share one Retry implementation", () => {
  const coachDir = path.resolve(__dirname, "../../app/(coach)/coach");
  const pages = walk(coachDir).filter((f) => !f.endsWith(".test.tsx"));

  it("no coach screen hand-rolls a Retry button", () => {
    const offenders = pages.filter((f) => {
      const src = readFileSync(f, "utf8");
      // A bare "Retry" JSX text line, or a "Retry" string label.
      return /^\s*Retry\s*$/m.test(src) || /["']Retry["']/.test(src);
    });
    expect(offenders).toEqual([]);
  });

  it("the known Retry screens render RetryButton", () => {
    const expected = [
      "calendar/page.tsx",
      "needs-review/page.tsx",
      "sessions/page.tsx",
      "sessions/[id]/skills/page.tsx",
      "students/[studentId]/passport/page.tsx",
      "today/page.tsx",
      "today/plan/page.tsx",
    ];
    for (const rel of expected) {
      const src = readFileSync(path.join(coachDir, rel), "utf8");
      expect(src, rel).toContain("<RetryButton");
    }
  });
});
