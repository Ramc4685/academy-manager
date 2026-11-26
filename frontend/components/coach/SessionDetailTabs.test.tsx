import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it } from "vitest";

import { SessionDetailTabs } from "./SessionDetailTabs";

describe("SessionDetailTabs", () => {
  it("has a Plan tab that opens the class date's teaching plan", () => {
    const html = renderToStaticMarkup(
      <SessionDetailTabs
        attendanceSkillsId="s1:2026-12-01:16:00"
        progressSessionId="s1"
        date="2026-12-01"
        active="attendance"
      />,
    );
    const tab = /<a[^>]*id="session-tab-plan"[^>]*>Plan</.exec(html)?.[0] ?? "";
    expect(tab).toContain('href="/coach/today/plan?date=2026-12-01"');
    expect(html).toContain('id="session-tab-attendance"');
  });
});
