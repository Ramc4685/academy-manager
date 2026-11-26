import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it } from "vitest";

import type { AdminMonthlyPayrollRow } from "@/lib/api/v2/payroll";

import { NO_CLASSES_NOTE, PayrollRows } from "./PayrollRows";

const row = (overrides: Partial<AdminMonthlyPayrollRow>): AdminMonthlyPayrollRow => ({
  coach_id: "coach-1",
  coach_name: "Demo Coach",
  session_count: 2,
  total_amount_cents: 4000,
  currency: "USD",
  status: "not_generated",
  period_id: null,
  unresolved_unpaid_count: 0,
  warning_count: 0,
  warning_status: "clear",
  ...overrides,
});

function html(rows: AdminMonthlyPayrollRow[]): string {
  return renderToStaticMarkup(
    <PayrollRows
      rows={rows}
      periodStart="2026-10-01T05:00:00Z"
      periodEnd="2026-11-01T05:00:00Z"
      generatePending={false}
      onGenerate={() => {}}
    />,
  );
}

function rowHtml(out: string, coachId: string): string {
  const start = out.indexOf(`data-testid="admin-payroll-row-${coachId}"`);
  const end = out.indexOf("</tr>", start);
  return out.slice(start, end);
}

describe("PayrollRows (S32: every active coach is listed)", () => {
  it("shows a coach who taught nothing muted, with no Generate", () => {
    const out = html([
      row({}),
      row({ coach_id: "casey", coach_name: "Casey Newcoach", session_count: 0, total_amount_cents: 0, generatable: false }),
    ]);
    const casey = rowHtml(out, "casey");
    expect(casey).toContain('data-muted="true"');
    expect(casey).toContain("Casey Newcoach");
    expect(casey).toContain(NO_CLASSES_NOTE);
    expect(casey).not.toContain("Generate");

    const demo = rowHtml(out, "coach-1");
    expect(demo).toContain("Generate");
    expect(demo).not.toContain(NO_CLASSES_NOTE);
  });
});
