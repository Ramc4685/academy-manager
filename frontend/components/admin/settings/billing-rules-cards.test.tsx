import { renderToStaticMarkup } from "react-dom/server";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { describe, expect, it, vi } from "vitest";

vi.mock("@/lib/api/admin", () => ({
  getAdminPaymentMethods: vi.fn(),
  getSelfServicePolicy: vi.fn(),
  updateAdminPaymentMethods: vi.fn(),
  updateSelfServicePolicy: vi.fn(),
}));
vi.mock("@/lib/api/v2/payroll", () => ({
  getPayrollSettings: vi.fn(),
  updatePayrollSettings: vi.fn(),
}));

import { queryKeys } from "@/lib/query/keys";
import { OfflinePaymentsCard } from "./offline-payments-card";
import { PayrollSettingsCard } from "./payroll-settings-card";

// S31: every card on Billing rules has its own Save, so each button names the card it saves.

function html(node: React.ReactNode, seed: (client: QueryClient) => void): string {
  const client = new QueryClient();
  seed(client);
  return renderToStaticMarkup(<QueryClientProvider client={client}>{node}</QueryClientProvider>);
}

describe("Billing rules card buttons", () => {
  it("the offline payments card says it saves the offline payment options", () => {
    const out = html(<OfflinePaymentsCard />, (client) => {
      client.setQueryData(queryKeys.admin.paymentMethods(), { manual_methods: ["cash"] });
      client.setQueryData(queryKeys.admin.selfServicePolicy(), { payment_instructions: "" });
    });
    expect(out).toContain("Save offline payment options");
    expect(out).toContain("Save payment instructions");
  });

  it("the payroll card says it saves the payroll settings", () => {
    const out = html(<PayrollSettingsCard />, (client) =>
      client.setQueryData(queryKeys.admin.payrollSettings(), {
        payroll_ach_discount_reduces_base: false,
        payroll_count_checkout_first_month: true,
        payroll_cancelled_class_share: "ran_only",
        payroll_missing_invoices: "block",
        payroll_assistant_pay_from: null,
      }),
    );
    expect(out).toContain("Save payroll settings");
    expect(out).not.toContain("Save coach payroll");
  });
});
