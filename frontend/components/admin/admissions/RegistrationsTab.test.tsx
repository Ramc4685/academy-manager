import { renderToStaticMarkup } from "react-dom/server";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { describe, expect, it, vi } from "vitest";

vi.mock("next/link", () => ({
  default: ({ href, children }: { href: string; children: React.ReactNode }) => (
    <a href={href}>{children}</a>
  ),
}));
vi.mock("@/lib/api/admin", () => ({ listAdminRegistrations: vi.fn() }));
vi.mock("@/lib/use-is-phone", () => ({ useIsPhone: () => false }));

import { queryKeys } from "@/lib/query/keys";
import { RegistrationsTab } from "./RegistrationsTab";

const row = {
  status: "PENDING_APPROVAL",
  parent_email: "p@example.com",
  parent_name: "Pat",
  selected_session_id: "s1",
  session_title: "Juniors Sat",
  zero_quote_period: null,
  family_notified_at: null,
  updated_at: "2026-09-29T00:00:00Z",
};

function html(registrations: Record<string, unknown>[]) {
  const client = new QueryClient();
  client.setQueryData(queryKeys.admin.registrations(), { registrations });
  return renderToStaticMarkup(
    <QueryClientProvider client={client}>
      <RegistrationsTab />
    </QueryClientProvider>,
  );
}

describe("RegistrationsTab waiver warning", () => {
  it("names the unsigned waivers on each queue row", () => {
    const out = html([
      {
        ...row,
        application_id: "app-1",
        student_name: "Ann",
        waiver_required: true,
        waiver_satisfied: false,
        unsigned_waivers: [
          { waiver_template_id: "wt-1", title: "Liability", version: "2" },
          { waiver_template_id: "wt-2", title: "Photo consent", version: "1" },
        ],
      },
      {
        ...row,
        application_id: "app-2",
        student_name: "Bo",
        waiver_required: true,
        waiver_satisfied: true,
        unsigned_waivers: [],
      },
      {
        ...row,
        application_id: "app-3",
        student_name: "Cy",
        waiver_required: false,
        waiver_satisfied: true,
      },
    ]);

    expect(out).toContain('data-testid="admin-registration-unsigned-waivers-app-1"');
    expect(out).toContain("UNSIGNED");
    expect(out).toContain("Liability, Photo consent");
    expect(out).not.toContain('data-testid="admin-registration-unsigned-waivers-app-2"');
    expect(out).not.toContain('data-testid="admin-registration-unsigned-waivers-app-3"');
    expect(out).toContain("SIGNED");
    expect(out).toContain("NOT REQUIRED");
  });
});
