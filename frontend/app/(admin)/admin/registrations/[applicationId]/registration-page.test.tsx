import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it, vi } from "vitest";

vi.mock("next/navigation", () => ({
  useParams: () => ({ applicationId: "app-1" }),
  useRouter: () => ({ push: () => {} }),
}));

import type { AdminRegistrationDetail } from "@/lib/api/admin";
import { queryKeys } from "@/lib/query/keys";

import AdminRegistrationDetailPage from "./page";

function render(detail: Partial<AdminRegistrationDetail>): string {
  const client = new QueryClient();
  client.setQueryData(queryKeys.admin.registrationDetail("app-1"), {
    application_id: "app-1",
    student_name: "Lucia Retest",
    parent_name: "Pat Retest",
    session_title: "Junior Skills Clinic",
    zero_quote_period: "2026-11",
    payment_id: null,
    unsigned_waivers: [],
    ...detail,
  });
  return renderToStaticMarkup(
    <QueryClientProvider client={client}>
      <AdminRegistrationDetailPage />
    </QueryClientProvider>,
  );
}

describe("admin registration review (S02 persona follow-up)", () => {
  it("asks for a decision while the registration is pending", () => {
    const html = render({ status: "PENDING_APPROVAL" });
    expect(html).toContain("Confirm the quote is correct before approving");
    expect(html).toContain("Decision");
    expect(html).not.toContain('data-testid="admin-registration-decided"');
  });

  it("says it was approved and drops the stale warning and decision cards", () => {
    const html = render({ status: "APPROVED" });
    expect(html).toContain("Approved. Lucia Retest is enrolled in Junior Skills Clinic");
    expect(html).not.toContain("Confirm the quote is correct before approving");
    expect(html).not.toContain("Approve registration");
    expect(html).not.toMatch(/>Decision</);
  });
});
