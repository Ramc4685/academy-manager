import { renderToStaticMarkup } from "react-dom/server";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { closeAcademyDates } from "@/lib/api/admin";
import * as client from "@/lib/api/client";

import { ClosureDatesCard } from "./closure-dates-card";

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
      expect.objectContaining({ method: "POST", body: JSON.stringify(body) }),
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
