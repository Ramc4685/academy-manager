import { renderToStaticMarkup } from "react-dom/server";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { describe, expect, it, vi } from "vitest";

vi.mock("@/lib/api/parent", () => ({ getParentAcademy: vi.fn() }));

import { queryKeys } from "@/lib/query/keys";
import { ContactAcademyCard } from "./contact-academy-card";

function html(academy: Record<string, unknown>) {
  const client = new QueryClient();
  client.setQueryData(queryKeys.parent.academy(), academy);
  return renderToStaticMarkup(
    <QueryClientProvider client={client}>
      <ContactAcademyCard />
    </QueryClientProvider>,
  );
}

describe("ContactAcademyCard", () => {
  it("shows tappable phone and email, hours, address and the message link", () => {
    const out = html({
      display_name: "Demo Academy",
      contact_phone: "(309) 555-0142",
      contact_email: "hello@demo.test",
      hours_text: "Mon–Sat 4–8 PM",
      address: "12 Court Lane, Normal IL",
    });
    expect(out).toContain("Contact the academy");
    expect(out).toContain('href="tel:(309) 555-0142"');
    expect(out).toContain('href="mailto:hello@demo.test"');
    expect(out).toContain("Mon–Sat 4–8 PM");
    expect(out).toContain("12 Court Lane, Normal IL");
    expect(out).toContain('href="/parent/messages#academy"');
  });

  it("still offers the message link when no contact details are set", () => {
    const out = html({ display_name: "Demo Academy", contact_phone: null, contact_email: null });
    expect(out).not.toContain("tel:");
    expect(out).toContain("Message the academy");
  });
});
