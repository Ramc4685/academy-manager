import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it } from "vitest";

import type { AdminSessionEconomicsResponse } from "@/lib/api/admin";

import AdminSessionEconomicsPage from "./page";

function period(): string {
  const now = new Date();
  return `${now.getFullYear()}-${String(now.getMonth() + 1).padStart(2, "0")}`;
}

const REPORT: AdminSessionEconomicsResponse = {
  period: period(),
  summary: {
    expected_revenue_cents: 72_000,
    paid_cents: 0,
    unpaid_cents: 72_000,
    coach_payroll_cents: 0,
    rent_cents: 0,
    other_expenses_cents: 0,
    payroll_status: "needs_payroll",
    payroll_blocked_by: "No generated payout periods for this month.",
    expected_profit_cents: null,
    profit_margin: null,
  },
  sessions: [
    {
      session_id: "sess-1",
      title: "Junior Beginners",
      coach_name: "Demo Coach, Casey Newcoach",
      active_enrollment_count: 9,
      not_billed_enrollment_count: 2,
      paid_student_count: 0,
      unpaid_student_count: 9,
      monthly_fee_cents: 8_000,
      payable_occurrence_count: 4,
      expected_revenue_per_occurrence_cents: 18_000,
      expected_revenue_cents: 72_000,
      paid_cents: 0,
      unpaid_cents: 72_000,
      coach_payroll_cents: 0,
      rent_cents: 0,
      other_expenses_cents: 0,
      payroll_status: "needs_payroll",
      expected_profit_cents: null,
      profit_margin: null,
    },
  ],
  empty_states: [],
};

function render(): string {
  const client = new QueryClient();
  client.setQueryData(["admin", "session-economics", period()], REPORT);
  return renderToStaticMarkup(
    <QueryClientProvider client={client}>
      <AdminSessionEconomicsPage />
    </QueryClientProvider>,
  );
}

describe("Session economics while payroll is not final", () => {
  it("shows Needs payroll and why instead of a profit", () => {
    const html = render();
    // KPI card and the class row both withhold the number.
    expect(html.match(/Needs payroll/g)).toHaveLength(2);
    expect(html).toContain("No generated payout periods for this month.");
    expect(html).not.toContain("Margin");
  });

  it("names the coaches and reads paying of enrolled", () => {
    const html = render();
    expect(html).toContain("Demo Coach, Casey Newcoach");
    expect(html).not.toContain("No coach assigned");
    expect(html).toContain("9 paying of 11 enrolled");
  });
});
