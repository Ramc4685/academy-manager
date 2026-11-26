import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it } from "vitest";

import { OwnerProvider } from "@/components/admin/owner-context";
import { queryKeys } from "@/lib/query/keys";

import { UnplacedBacklog } from "./unplaced-backlog";

function render(isOwner: boolean, names: string[]): string {
  const client = new QueryClient({ defaultOptions: { queries: { staleTime: Infinity } } });
  client.setQueryData(queryKeys.admin.pathwayUnplaced(), {
    program_id: "prog-1",
    students: names.map((n, i) => ({ student_id: `st-${i}`, student_name: n })),
  });
  return renderToStaticMarkup(
    <QueryClientProvider client={client}>
      <OwnerProvider isOwner={isOwner}>
        <UnplacedBacklog firstLevelName="Foundations" />
      </OwnerProvider>
    </QueryClientProvider>,
  );
}

describe("UnplacedBacklog (S52)", () => {
  it("lists every unplaced student before the owner's place-all button", () => {
    const html = render(true, ["Tej Walkin", "Noor Haddad"]);
    expect(html).toContain("Tej Walkin");
    expect(html).toContain("Noor Haddad");
    expect(html).toContain("Place all on Foundations");
  });

  it("shows an admin the list but no button", () => {
    const html = render(false, ["Tej Walkin"]);
    expect(html).toContain("Tej Walkin");
    expect(html).not.toContain('data-testid="pathway-place-backlog"');
    expect(html).toContain("The academy owner can place them");
  });

  it("renders nothing once nobody is unplaced", () => {
    expect(render(true, [])).toBe("");
  });
});
