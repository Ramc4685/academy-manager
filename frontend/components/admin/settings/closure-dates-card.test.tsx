import { renderToStaticMarkup } from "react-dom/server";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { closeAcademyDates } from "@/lib/api/admin";
import * as client from "@/lib/api/client";

import { ClosureDatesCard, ClosurePreview, ClosureResult } from "./closure-dates-card";

describe("closeAcademyDates (L12)", () => {
  beforeEach(() => vi.restoreAllMocks());

  it("POSTs the local date range, reason and preview flag to /admin/closures", async () => {
    const spy = vi.spyOn(client, "apiFetch").mockResolvedValue({ dates: [] } as never);
    const body = {
      start_date: "2026-11-26",
      end_date: "2026-11-29",
      reason: "Thanksgiving",
      notify: true,
      dry_run: true,
    };
    await closeAcademyDates(body);
    expect(spy).toHaveBeenCalledWith(
      "/admin/closures",
      expect.objectContaining({
        method: "POST",
        body: JSON.stringify(body),
        timeoutMs: 120_000,
      }),
    );
  });
});

describe("ClosureDatesCard", () => {
  it("starts with the range form and a disabled preview, nothing cancelled", () => {
    const out = renderToStaticMarkup(
      <QueryClientProvider client={new QueryClient()}>
        <ClosureDatesCard />
      </QueryClientProvider>,
    );
    expect(out).toContain('data-testid="closure-start"');
    expect(out).toContain('data-testid="closure-end"');
    expect(out).toContain('data-testid="closure-reason"');
    expect(out).toMatch(/data-testid="closure-preview"[^>]*disabled|disabled[^>]*data-testid="closure-preview"/);
    expect(out).not.toContain('data-testid="closure-apply"');
  });
});

// 2026-11-26 23:00 UTC is 5:00 PM in Chicago but already Friday in Tokyo.
const THURSDAY_EVENING = "2026-11-26T23:00:00Z";

function date(overrides: Record<string, unknown>) {
  return {
    occurrence_id: "occ-1",
    session_id: "sess-1",
    session_title: "Juniors",
    start_at: THURSDAY_EVENING,
    status: "would_cancel",
    credits_issued: 0,
    ...overrides,
  } as never;
}

describe("ClosurePreview", () => {
  it("lists the dates to cancel in the academy timezone and the refused ones apart", () => {
    const out = renderToStaticMarkup(
      <ClosurePreview
        pending={false}
        onApply={() => {}}
        preview={{
          timezone: "America/Chicago",
          dates: [
            date({}),
            date({
              occurrence_id: "occ-2",
              status: "skipped",
              skip_reason: "inside an approved payout period",
            }),
          ],
        }}
      />,
    );
    expect(out).toContain("1 class date will be cancelled");
    expect(out).toContain("Thu, Nov 26");
    expect(out).not.toContain("Fri, Nov 27");
    expect(out).toContain("Not cancelled: Juniors");
    expect(out).toContain("inside an approved payout period");
    expect(out).toContain("Cancel 1 class date");
  });

  it("offers no cancel button when every date is refused", () => {
    const out = renderToStaticMarkup(
      <ClosurePreview
        pending={false}
        onApply={() => {}}
        preview={{ timezone: "America/Chicago", dates: [date({ status: "skipped" })] }}
      />,
    );
    expect(out).toContain("No weekly classes can be cancelled");
    expect(out).not.toContain('data-testid="closure-apply"');
  });
});

describe("ClosureResult", () => {
  it("shows billing warnings and families with no email on file", () => {
    const out = renderToStaticMarkup(
      <ClosureResult
        notify
        done={{
          timezone: "America/Chicago",
          cancelled: 1,
          credits_issued: 0,
          families_affected: 3,
          families_notified: 2,
          notice_failed: false,
          dates: [date({ status: "cancelled", billing_warning: "Billing did not run." })],
        }}
      />,
    );
    expect(out).toContain("1 class date cancelled, 2 families emailed.");
    expect(out).toContain("1 family on these classes has no email on file");
    expect(out).toContain("Billing did not run.");
  });

  it("tells the admin when the family emails failed", () => {
    const out = renderToStaticMarkup(
      <ClosureResult
        notify
        done={{
          timezone: "America/Chicago",
          cancelled: 2,
          families_affected: 2,
          families_notified: 0,
          notice_failed: true,
          dates: [],
        }}
      />,
    );
    expect(out).toContain('data-testid="closure-notice-failed"');
    expect(out).not.toContain('data-testid="closure-not-emailed"');
  });
});
