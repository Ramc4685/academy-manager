import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it } from "vitest";

import { queryKeys } from "@/lib/query/keys";

import { academyContactLine, CoachEmptyState } from "./CoachEmptyState";

const base = { name: "Riverside", logo_url: null, brand_color: null };

describe("academy contact line", () => {
  it("names whichever contact the academy set", () => {
    expect(academyContactLine({ ...base, contact_phone: "555-0100" })).toBe("Questions? Call 555-0100.");
    expect(academyContactLine({ ...base, contact_email: "office@example.com" })).toBe(
      "Questions? Email office@example.com.",
    );
    expect(academyContactLine({ ...base, contact_phone: " ", contact_email: null })).toBeNull();
    expect(academyContactLine(undefined)).toBeNull();
  });
});

describe("CoachEmptyState", () => {
  it("drops the contact line when the academy set none", () => {
    const client = new QueryClient();
    client.setQueryData(queryKeys.coach.academy(), base);
    const html = renderToStaticMarkup(
      <QueryClientProvider client={client}>
        <CoachEmptyState />
      </QueryClientProvider>,
    );
    expect(html).toContain("Classes appear here once the academy assigns them.");
    expect(html).not.toContain("academy-contact");
  });
});
