import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it, vi } from "vitest";

vi.mock("@/lib/api/admin", () => ({ listAdminAiVideoConsents: vi.fn() }));

import { AiVideoConsentStatusList } from "./ai-video-consent-status";

describe("AiVideoConsentStatusList", () => {
  it("lists each child's status read-only", () => {
    const html = renderToStaticMarkup(
      <AiVideoConsentStatusList
        rows={[
          { student_id: "st-1", student_name: "Kid One", status: "granted", text_version: "v0" },
          { student_id: "st-2", student_name: "Kid Two", status: "revoked" },
        ]}
      />,
    );
    expect(html).toContain("Kid One");
    expect(html).toContain("Opted in");
    expect(html).toContain("Revoked");
    expect(html).not.toContain("<button");
  });

  it("says so when nobody opted in", () => {
    expect(renderToStaticMarkup(<AiVideoConsentStatusList rows={[]} />)).toContain(
      "No parent has opted a child in.",
    );
  });
});
