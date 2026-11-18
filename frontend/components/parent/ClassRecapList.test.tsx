import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it } from "vitest";

import { ClassRecapItems } from "./ClassRecapList";

const render = (recaps: Parameters<typeof ClassRecapItems>[0]["recaps"]) =>
  renderToStaticMarkup(
    <ClassRecapItems recaps={recaps} firstName="Maya" timeZone="America/Chicago" />,
  );

describe("parent class recap", () => {
  it("separates what the class worked on from what the child practised", () => {
    const html = render([
      {
        occurrence_id: "occ-1",
        class_starts_at: "2026-11-18T20:00:00Z",
        taught_skills: ["Forehand grip", "Jump smash"],
        practiced_skills: ["Forehand grip"],
        passed_skills: [],
      },
    ]);
    expect(html).toContain("Class worked on: ");
    expect(html).toContain("Maya practised: ");
    expect(html).toContain("Wed, Nov 18");
    expect(html).not.toContain("✓");
  });

  it("labels a pass as current status, not as earned at that class", () => {
    const html = render([
      {
        occurrence_id: "occ-1",
        class_starts_at: "2026-11-04T20:00:00Z",
        taught_skills: ["Forehand grip"],
        practiced_skills: ["Forehand grip"],
        passed_skills: ["Forehand grip"],
      },
    ]);
    expect(html).toContain("Forehand grip ✓");
    expect(html).toContain("has passed that skill as of today");
    expect(html).toContain("may have been passed at a later");
  });

  it("taught-only class never implies the child practised", () => {
    const html = render([
      {
        occurrence_id: "occ-1",
        class_starts_at: "2026-11-18T20:00:00Z",
        taught_skills: ["Serve"],
        practiced_skills: [],
        passed_skills: [],
      },
    ]);
    expect(html).toContain("did not record which skills Maya practised");
    expect(html).not.toContain("Maya practised:");
  });
});
