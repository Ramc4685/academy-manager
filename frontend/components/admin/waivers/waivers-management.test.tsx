import { renderToStaticMarkup } from "react-dom/server";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { describe, expect, it, vi } from "vitest";

vi.mock("next/link", () => ({
  default: ({ href, children }: { href: string; children: React.ReactNode }) => (
    <a href={href}>{children}</a>
  ),
}));
vi.mock("@/lib/api/admin", () => ({
  assignAdminWaiverTemplate: vi.fn(),
  createAdminWaiverTemplate: vi.fn(),
  listAdminWaivers: vi.fn(),
  listAdminWaiverTemplates: vi.fn(),
  publishAdminWaiverTemplate: vi.fn(),
}));

import { queryKeys } from "@/lib/query/keys";
import { WaiversManagement } from "./waivers-management";

const base = {
  body: "text",
  content_hash: "h",
  effective_at: null,
  published_at: null,
  assigned_at: null,
  updated_at: "2026-09-29T00:00:00Z",
};

function html(templates: Record<string, unknown>[], programs: unknown[] = []) {
  const client = new QueryClient();
  client.setQueryData(queryKeys.admin.waivers(), {
    summary: { signed_current: 0, pending_signature: 0, expiring_30d: 0, outdated_version: 0 },
    current_waiver: null,
    waivers: [],
  });
  client.setQueryData(queryKeys.admin.waiverTemplates(), { templates, programs });
  return renderToStaticMarkup(
    <QueryClientProvider client={client}>
      <WaiversManagement />
    </QueryClientProvider>,
  );
}

describe("WaiversManagement waiver list", () => {
  it("lists each waiver with version, Live or Draft, and who signs it", () => {
    const out = html(
      [
        {
          ...base,
          waiver_template_id: "wt-liability",
          title: "Liability waiver",
          status: "active",
          version: "3",
          assigned_to_registration: true,
        },
        {
          ...base,
          waiver_template_id: "wt-photo",
          title: "Photo & media consent",
          status: "active",
          version: "1",
          assigned_to_registration: false,
          required: true,
          scope: "programs",
          program_ids: ["prog-juniors"],
        },
        {
          ...base,
          waiver_template_id: "wt-draft",
          title: "Travel release",
          status: "draft",
          version: null,
          assigned_to_registration: false,
        },
      ],
      [{ program_id: "prog-juniors", name: "Juniors" }],
    );

    expect(out).toContain("Liability waiver");
    expect(out).toContain("v3");
    expect(out).toContain("Required for: All families");
    expect(out).toContain("Required for: Juniors");
    expect(out).toContain("LIVE");
    expect(out).toContain("DRAFT");
    // A draft has nothing to assign until it is published.
    expect(out).toContain("Publish to assign");
    expect(out).toContain('data-testid="admin-waiver-assign-button-wt-liability"');
    expect(out).toContain('data-testid="admin-waiver-assign-button-wt-photo"');
    expect(out).not.toContain('data-testid="admin-waiver-assign-button-wt-draft"');
    expect(out).toContain('data-testid="admin-waiver-new-version-wt-liability"');
    expect(out).toContain('data-testid="admin-waiver-publish-wt-draft"');
  });

  it("keeps superseded versions out of the main list", () => {
    const out = html([
      {
        ...base,
        waiver_template_id: "wt-old",
        title: "Liability waiver",
        status: "superseded",
        version: "2",
        assigned_to_registration: false,
      },
      {
        ...base,
        waiver_template_id: "wt-new",
        title: "Liability waiver",
        status: "active",
        version: "3",
        assigned_to_registration: true,
      },
    ]);

    expect(out).toContain('data-testid="admin-waiver-older"');
    expect(out).toContain("Older versions (1)");
    expect(out).not.toContain('data-testid="admin-waiver-assign-button-wt-old"');
  });

  it("says so when no waiver exists", () => {
    expect(html([])).toContain("admin-waiver-templates-empty");
  });
});
