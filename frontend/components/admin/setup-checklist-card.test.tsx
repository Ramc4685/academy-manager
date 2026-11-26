import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it } from "vitest";

import type { SetupChecklist } from "@/lib/api/admin";
import { queryKeys } from "@/lib/query/keys";

import { SetupChecklistCard } from "./setup-checklist-card";

function render(data: SetupChecklist): string {
  const client = new QueryClient({ defaultOptions: { queries: { staleTime: Infinity } } });
  client.setQueryData(queryKeys.admin.setupChecklist(), data);
  return renderToStaticMarkup(
    <QueryClientProvider client={client}>
      <SetupChecklistCard />
    </QueryClientProvider>,
  );
}

const step = (key: SetupChecklist["items"][number]["key"], status: "done" | "todo", label: string) => ({
  key,
  label,
  detail: `${label} detail.`,
  status,
  href: "/admin/settings?panel=academy",
  owner_only: false,
});

describe("SetupChecklistCard (S09)", () => {
  it("is one collapsed line that lists only the steps left", () => {
    const html = render({
      items: [step("academy_profile", "done", "Academy details"), step("waiver", "todo", "Waiver")],
      done_count: 1,
      total: 2,
      complete: false,
    });
    // A closed <details>: only the summary line shows until opened.
    expect(html).toMatch(/<details data-testid="dashboard-setup-checklist-details">/);
    expect(html).not.toMatch(/<details[^>]*\sopen/);
    expect(html).toContain("1 of 2 steps done");
    expect(html).toContain('data-testid="setup-step-waiver"');
    expect(html).not.toContain('data-testid="setup-step-academy_profile"');
  });

  it("renders nothing once every step is done", () => {
    const html = render({
      items: [step("waiver", "done", "Waiver")],
      done_count: 1,
      total: 1,
      complete: true,
    });
    expect(html).toBe("");
  });
});
