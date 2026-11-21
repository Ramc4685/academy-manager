import { renderToStaticMarkup } from "react-dom/server";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { describe, expect, it, vi } from "vitest";

vi.mock("next/navigation", () => ({ useParams: () => ({ studentId: "stu-1", certId: "c1" }) }));
vi.mock("@/lib/use-native-app", () => ({ useIsNativeApp: () => false }));
vi.mock("@/components/progress/level-certificate", () => ({ CertificatePreview: () => null }));

import type { CertificateDetail, SkillCertificate } from "@/lib/api/curriculum";
import { queryKeys } from "@/lib/query/keys";
import AdminCertificatePage from "./page";

function render(cert: Partial<SkillCertificate>) {
  const client = new QueryClient();
  client.setQueryData(["admin", "certificate", "stu-1", "c1"], {
    certificate: {
      cert_id: "c1",
      student_id: "stu-1",
      cert_number: "BLNO-C-0007",
      student_name: "Kid",
      level_name: "Level 1",
      program_name: "Juniors",
      completed_at: "2026-11-01T00:00:00Z",
      issued_at: "2026-11-01T00:00:00Z",
      status: "issued",
      ...cert,
    },
    level_number: 1,
    skills: [],
    next_level: null,
    levels: [],
  } satisfies CertificateDetail);
  client.setQueryData(queryKeys.admin.academy(), { display_name: "Academy" });
  return renderToStaticMarkup(
    <QueryClientProvider client={client}>
      <AdminCertificatePage />
    </QueryClientProvider>,
  );
}

describe("admin certificate page", () => {
  it("offers Revoke and Print on an issued certificate", () => {
    const out = render({});
    expect(out).toContain(">Revoke</button>");
    expect(out).toContain("Print or save as PDF");
    expect(out).not.toContain("certificate-revoked-banner");
  });

  it("shows why a revoked certificate was taken back, with no Revoke or Print", () => {
    const out = render({
      status: "revoked",
      revoked_at: "2026-11-10T12:00:00Z",
      revoke_reason: "approved by mistake",
    });
    expect(out).toContain('data-testid="certificate-revoked-banner"');
    expect(out).toContain(": approved by mistake");
    expect(out).not.toContain(">Revoke</button>");
    expect(out).not.toContain("Print or save as PDF");
  });
});
