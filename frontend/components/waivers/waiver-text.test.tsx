import { createElement } from "react";
import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it } from "vitest";

import { WaiverText } from "./waiver-text";

const body = "## Rules [initials]\nBe kind.\n## Adult release [adult] [initials]\nGrown-ups.";

describe("WaiverText", () => {
  it("asks for initials only on the sections it is told to", () => {
    const html = renderToStaticMarkup(createElement(WaiverText, { body, needInitials: ["s1"] }));
    expect(html).toContain("Initials for Rules");
    expect(html).not.toContain("Initials for Adult release");
    expect(html).toContain("Participants 18 and over");
  });

  it("says so when there is no text", () => {
    expect(renderToStaticMarkup(createElement(WaiverText, { body: "" }))).toContain(
      "Waiver text is not available.",
    );
  });
});
