import { createElement } from "react";
import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it } from "vitest";

import type { ParentAiVideoConsentView } from "@/lib/api/parent";
import { AiVideoConsentBlock } from "./ai-video-consent";

// Fictional fixture: no real family.
const view: ParentAiVideoConsentView = {
  text_version: "ai_video_consent_v0_placeholder",
  text: "PLACEHOLDER TEXT. [vendor to be confirmed] ... [30, 60 or 90] days.",
  placeholder: true,
  children: [
    { student_id: "st-1", student_name: "Kid One", status: "none" },
    {
      student_id: "st-2",
      student_name: "Kid Two",
      status: "granted",
      text_version: "ai_video_consent_v0_placeholder",
      accepted_at: "2026-11-05T12:00:00Z",
    },
    { student_id: "st-3", student_name: "Kid Three", status: "revoked" },
  ],
};

function render(over: Partial<ParentAiVideoConsentView> = {}): string {
  return renderToStaticMarkup(
    createElement(AiVideoConsentBlock, {
      view: { ...view, ...over },
      busyStudentId: null,
      error: null,
      onGrant: () => {},
      onRevoke: () => {},
    }),
  );
}

describe("AiVideoConsentBlock", () => {
  it("shows the versioned text and flags the placeholder", () => {
    const html = render();
    expect(html).toContain("[vendor to be confirmed]");
    expect(html).toContain("Version ai_video_consent_v0_placeholder");
    expect(html).toContain("draft awaiting legal review");
    expect(render({ placeholder: false })).not.toContain("draft awaiting legal review");
  });

  it("starts unticked with Opt in disabled for a child without consent", () => {
    const html = render();
    expect(html).not.toMatch(/type="checkbox"[^>]*checked/);
    expect(html).toMatch(/<button[^>]*disabled[^>]*>Opt in<\/button>/);
  });

  it("offers Revoke for an opted-in child and marks a revoked one", () => {
    const html = render();
    expect(html).toContain("Opted in");
    expect(html).toMatch(/<button[^>]*>Revoke<\/button>/);
    expect(html).toContain("Revoked");
  });
});
