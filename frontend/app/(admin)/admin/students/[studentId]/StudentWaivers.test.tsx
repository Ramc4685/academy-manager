import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it } from "vitest";

import type { AdminStudentWaiverRow } from "@/lib/api/admin";

import { StudentWaiversPanel, StudentWaiverWarning } from "./StudentWaivers";

const row = (
  id: string,
  title: string,
  status: AdminStudentWaiverRow["status"],
  extra: Partial<AdminStudentWaiverRow> = {},
): AdminStudentWaiverRow => ({
  waiver_template_id: id,
  lineage_key: `wl-${id}`,
  title,
  version: "2",
  status,
  signed_version: null,
  signed_at: null,
  signature_id: null,
  ...extra,
});

describe("StudentWaiverWarning", () => {
  it("names every waiver that is not signed at the live version and says it does not block", () => {
    const out = renderToStaticMarkup(
      <StudentWaiverWarning
        rows={[
          row("a", "Liability waiver", "signed", { signed_version: "2" }),
          row("b", "Photo consent", "unsigned"),
          row("c", "Travel release", "older_version", { signed_version: "1" }),
        ]}
      />,
    );
    expect(out).toContain('data-testid="admin-student-waiver-warning"');
    expect(out).toContain("Photo consent, Travel release");
    expect(out).not.toContain("Liability waiver");
    expect(out).toContain("does not block enrollment");
  });

  it("renders nothing when every waiver is signed or none applies", () => {
    expect(
      renderToStaticMarkup(<StudentWaiverWarning rows={[row("a", "Liability", "signed")]} />),
    ).toBe("");
    expect(renderToStaticMarkup(<StudentWaiverWarning rows={[]} />)).toBe("");
  });
});

describe("StudentWaiversPanel", () => {
  it("shows one row per waiver with its status and a link to the signature", () => {
    const out = renderToStaticMarkup(
      <StudentWaiversPanel
        loading={false}
        error={false}
        rows={[
          row("a", "Liability waiver", "signed", {
            signed_version: "2",
            signed_at: "2026-09-20T12:00:00Z",
            signature_id: "ws-1",
          }),
          row("b", "Photo consent", "older_version", { signed_version: "1", signature_id: "ws-2" }),
          row("c", "Travel release", "unsigned"),
        ]}
      />,
    );
    expect(out).toContain('data-testid="admin-student-waiver-a"');
    expect(out).toContain("Signed v2");
    expect(out).toContain("Signed an older version (v1)");
    expect(out).toContain("Not signed");
    expect(out).toContain("/admin/waivers/signatures/ws-1");
    expect(out).toContain("/admin/waivers/signatures/ws-2");
    // No signature, no link.
    expect(out.match(/View signature/g)?.length).toBe(2);
  });

  it("says so when no waiver applies, and when loading or failing", () => {
    expect(
      renderToStaticMarkup(<StudentWaiversPanel loading={false} error={false} rows={[]} />),
    ).toContain("admin-student-waivers-empty");
    expect(
      renderToStaticMarkup(<StudentWaiversPanel loading error={false} rows={[]} />),
    ).toContain("Loading waivers");
    expect(
      renderToStaticMarkup(<StudentWaiversPanel loading={false} error rows={[]} />),
    ).toContain("Could not load waivers");
  });
});
