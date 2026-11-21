import { readFileSync } from "node:fs";
import path from "node:path";
import { describe, expect, it } from "vitest";

// node-env vitest (no DOM): pin the panel's data source and dropped tiles by source.
const panel = readFileSync(path.join(__dirname, "PayslipsPanel.tsx"), "utf8");
const page = readFileSync(path.join(__dirname, "..", "page.tsx"), "utf8");

describe("Payslips panel (L7)", () => {
  it("reads the picked month from the monthly payroll list", () => {
    expect(panel).toContain("listMonthlyPayroll(month)");
    expect(page).toContain("<PayslipsPanel month={month} />");
  });

  it("no longer calls the deleted payouts route or shows students and expected revenue", () => {
    expect(panel).not.toMatch(/listPayouts|students|expected revenue|expectedRevenue/i);
  });
});
