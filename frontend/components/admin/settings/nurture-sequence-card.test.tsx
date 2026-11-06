import { renderToStaticMarkup } from "react-dom/server";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { describe, expect, it, vi } from "vitest";

vi.mock("@/lib/api/admin", () => ({
  getAdminNurtureSequence: vi.fn(),
  updateAdminNurtureSequence: vi.fn(),
  previewAdminNurtureStep: vi.fn(),
}));

import type { NurtureSequenceView } from "@/lib/api/admin";
import { queryKeys } from "@/lib/query/keys";

import { NurtureSequenceCard } from "./nurture-sequence-card";

const BLANK: NurtureSequenceView = {
  enabled: false,
  enabled_at: null,
  steps: [
    { day: 2, subject: "", body: "" },
    { day: 7, subject: "", body: "" },
    { day: 21, subject: "", body: "" },
  ],
  merge_fields: ["academy_name", "class", "seat_band", "booking_link"],
};

function html(view: NurtureSequenceView) {
  const client = new QueryClient();
  client.setQueryData(queryKeys.admin.nurtureSequence(), view);
  return renderToStaticMarkup(
    <QueryClientProvider client={client}>
      <NurtureSequenceCard />
    </QueryClientProvider>,
  );
}

describe("NurtureSequenceCard (Phase 3 C1)", () => {
  it("is off by default with an editor for days 2, 7 and 21 and the merge fields", () => {
    const out = html(BLANK);
    expect(out).toMatch(/data-testid="nurture-enabled"(?![^>]*checked)/);
    for (const day of [2, 7, 21]) expect(out).toContain(`data-testid="nurture-day-${day}"`);
    expect(out).toContain("{{academy_name}}, {{class}}, {{seat_band}}, {{booking_link}}");
    // Nothing to save until something changes.
    expect(out).toMatch(/<button[^>]*disabled=""[^>]*data-testid="nurture-save"|<button[^>]*data-testid="nurture-save"[^>]*disabled=""/);
  });

  it("shows the saved switch and text", () => {
    const out = html({
      ...BLANK,
      enabled: true,
      enabled_at: "2026-11-05T12:00:00Z",
      steps: [{ day: 2, subject: "Still thinking about {{class}}?", body: "Hi" }, ...BLANK.steps.slice(1)],
    });
    expect(out).toMatch(/data-testid="nurture-enabled"[^>]*checked/);
    expect(out).toContain('value="Still thinking about {{class}}?"');
  });
});
