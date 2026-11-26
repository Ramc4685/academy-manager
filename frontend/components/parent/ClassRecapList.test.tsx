import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it } from "vitest";

import { ClassRecapItems } from "./ClassRecapList";

const skill = (skill_id: string, name: string) => ({ skill_id, name });

const render = (recaps: Parameters<typeof ClassRecapItems>[0]["recaps"]) =>
  renderToStaticMarkup(
    <ClassRecapItems recaps={recaps} firstName="Maya" timeZone="America/Chicago" />,
  );

const row = (over: Partial<Parameters<typeof ClassRecapItems>[0]["recaps"][number]>) => ({
  occurrence_id: "occ-1",
  class_starts_at: "2026-11-18T20:00:00Z",
  taught_skills: [skill("g", "Forehand grip")],
  practiced_skills: [],
  earned_skills: [],
  ...over,
});

describe("parent class timeline", () => {
  it("separates the class lesson from what the child practised", () => {
    const html = render([
      row({
        taught_skills: [skill("g", "Forehand grip"), skill("s", "Jump smash")],
        practiced_skills: [skill("g", "Forehand grip")],
      }),
    ]);
    expect(html).toContain("Class lesson: Forehand grip, Jump smash");
    expect(html).toContain("Maya practised: Forehand grip");
    expect(html).toContain("Wed, Nov 18, 2026");
    expect(html).not.toContain("Passed at this class");
  });

  it("shows a pass only on the class that earned it, repeated practice on both", () => {
    const html = render([
      row({
        occurrence_id: "occ-2",
        class_starts_at: "2026-11-25T20:00:00Z",
        practiced_skills: [skill("g", "Forehand grip")],
        earned_skills: [skill("g", "Forehand grip")],
      }),
      row({ practiced_skills: [skill("g", "Forehand grip")] }),
    ]);
    expect(html.match(/Maya practised: Forehand grip/g)).toHaveLength(2);
    expect(html.match(/Passed at this class: Forehand grip/g)).toHaveLength(1);
    expect(html.indexOf("Nov 25")).toBeLessThan(html.indexOf("Passed at this class"));
    expect(html.indexOf("Passed at this class")).toBeLessThan(html.indexOf("Nov 18"));
  });

  it("a group-only lesson never implies the child practised", () => {
    const html = render([row({ taught_skills: [skill("sv", "Serve")] })]);
    // S18: no negative "the coach did not record" line either.
    expect(html).not.toContain("did not record");
    expect(html).not.toContain("Maya practised:");
  });
});
