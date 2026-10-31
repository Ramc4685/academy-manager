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
import { AssignPanel, WaiversManagement } from "./waivers-management";

const base = {
  body: "text",
  content_hash: "h",
  effective_at: null,
  published_at: null,
  assigned_at: null,
  updated_at: "2026-09-29T00:00:00Z",
};

const emptySummary = {
  signed_current: 0,
  pending_signature: 0,
  expiring_30d: 0,
  outdated_version: 0,
};

function html(
  templates: Record<string, unknown>[],
  programs: unknown[] = [],
  report: Record<string, unknown> = {},
) {
  const client = new QueryClient();
  client.setQueryData(queryKeys.admin.waivers(), {
    summary: emptySummary,
    current_waiver: null,
    waivers: [],
    ...report,
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


function lineage(key: string, title: string, over: Record<string, unknown> = {}) {
  return {
    lineage_key: key,
    waiver: { waiver_id: `wt-${key}`, title, version: "1" },
    required: true,
    scope: "all",
    program_ids: [],
    summary: { ...emptySummary, signed_current: 2, pending_signature: 1, active_students: 3 },
    waivers: [
      {
        waiver_id: "st-1:1",
        student_id: "st-1",
        student_name: "Ann Lee",
        parent_id: "p",
        parent_name: "Pat Lee",
        parent_email: null,
        status: "signed",
        version: "1",
        signed_at: null,
        method: null,
        expires_at: null,
      },
    ],
    ...over,
  };
}

describe("WaiversManagement per-waiver report", () => {
  it("keeps the single-waiver layout when one waiver is live", () => {
    const out = html([], [], { lineages: [lineage("legacy", "Liability")] });

    expect(out).not.toContain('data-testid="admin-waivers-lineages"');
    expect(out).toContain("Current waiver");
    expect(out).toContain("Per-student status");
  });

  it("shows counts and rows per waiver when several are live", () => {
    const out = html(
      [],
      [{ program_id: "prog-juniors", name: "Juniors" }],
      {
        lineages: [
          lineage("legacy", "Liability"),
          lineage("photo", "Photo consent", {
            scope: "programs",
            program_ids: ["prog-juniors"],
            summary: { ...emptySummary, pending_signature: 1, active_students: 1 },
            waivers: [],
          }),
        ],
      },
    );

    expect(out).toContain('data-testid="admin-waivers-lineage-legacy"');
    expect(out).toContain('data-testid="admin-waivers-lineage-photo"');
    expect(out).toContain("Photo consent v1");
    expect(out).toContain("Required for: All families");
    expect(out).toContain("Required for: Juniors");
    expect(out).toContain('data-testid="admin-waivers-row-legacy-st-1:1"');
    expect(out).toContain('data-testid="admin-waivers-lineage-empty-photo"');
    expect(out).toContain("Template management");
  });
});

describe("AssignPanel archived programs", () => {
  const template = {
    ...base,
    waiver_template_id: "wt-photo",
    title: "Photo consent",
    status: "active",
    version: "1",
    assigned_to_registration: false,
    required: true,
    scope: "programs" as const,
    program_ids: ["prog-old"],
  };

  function panel(programs: { program_id: string; name: string; archived?: boolean }[]) {
    return renderToStaticMarkup(
      <AssignPanel
        template={template as never}
        programs={programs}
        pending={false}
        failed={false}
        onCancel={() => undefined}
        onSave={() => undefined}
      />,
    );
  }

  it("lists an assigned-but-archived program as Archived: name so it can be removed", () => {
    const out = panel([
      { program_id: "prog-juniors", name: "Juniors" },
      { program_id: "prog-old", name: "Old squad", archived: true },
    ]);

    expect(out).toContain("Archived: Old squad");
    expect(out).toContain('data-testid="admin-waiver-assign-program-wt-photo-prog-old"');
    expect(out).toContain('data-testid="admin-waiver-assign-archived-note-wt-photo"');
    // Saving is held until the archived program is unticked.
    expect(out).toMatch(/data-testid="admin-waiver-assign-save-wt-photo"[^>]*disabled|disabled=""[^>]*admin-waiver-assign-save-wt-photo/);
  });

  it("does not offer an archived program that this waiver is not assigned to", () => {
    const out = panel([
      { program_id: "prog-juniors", name: "Juniors" },
      { program_id: "prog-unused", name: "Unused squad", archived: true },
    ]);

    expect(out).not.toContain("Unused squad");
  });
});
