import { renderToStaticMarkup } from "react-dom/server";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { describe, expect, it, vi } from "vitest";

vi.mock("@/lib/api/admin", () => ({ getAdminPlatformFee: vi.fn() }));

import { queryKeys } from "@/lib/query/keys";
import { ProcessingFeeCard } from "./processing-fee-card";

const AGREEMENT =
  "Core operations (rosters, attendance, billing, the parent app, the pipeline board and templated messages) are free.";

function html(fee: Record<string, unknown>) {
  const client = new QueryClient();
  client.setQueryData(queryKeys.admin.platformFee(), fee);
  return renderToStaticMarkup(
    <QueryClientProvider client={client}>
      <ProcessingFeeCard />
    </QueryClientProvider>,
  );
}

describe("ProcessingFeeCard", () => {
  it("shows the rate, the agreement and who accepted it", () => {
    const out = html({
      application_fee_bps: 100,
      agreement_version: "2026-11-04",
      agreement_text: AGREEMENT,
      accepted_at: "2026-11-04T15:00:00Z",
      accepted_by: "Jane Owner",
    });
    expect(out).toContain(
      "CourtMastr processing fee: 1.00% of card and ACH payments. Parents are not charged a per-order fee.",
    );
    expect(out).toContain(AGREEMENT);
    expect(out).toContain("accepted by Jane Owner");
    expect(out).not.toContain("forever");
  });

  it("says when the agreement has not been accepted yet", () => {
    const out = html({
      application_fee_bps: 0,
      agreement_version: null,
      agreement_text: AGREEMENT,
      accepted_at: null,
      accepted_by: null,
    });
    expect(out).toContain("0.00%");
    expect(out).toContain("Agreement not yet accepted.");
  });

  it("treats a payload without a rate as not loaded, never NaN", () => {
    const out = html({});
    expect(out).toContain("Could not load the processing fee.");
    expect(out).not.toContain("NaN");
  });
});
