import { renderToStaticMarkup } from "react-dom/server";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { describe, expect, it, vi } from "vitest";

vi.mock("@/lib/api/admin", () => ({ getAdminAcademy: vi.fn() }));

import { queryKeys } from "@/lib/query/keys";
import { EmailSendingCard } from "./email-sending-card";

function html(academy: Record<string, unknown>) {
  const client = new QueryClient();
  client.setQueryData(queryKeys.admin.academy(), academy);
  return renderToStaticMarkup(
    <QueryClientProvider client={client}>
      <EmailSendingCard />
    </QueryClientProvider>,
  );
}

describe("EmailSendingCard", () => {
  it("falls back to the display name and shows the empty reply-to state", () => {
    const out = html({ display_name: "BLNO", email_sender_name: " ", email_reply_to: "" });
    expect(out).toContain("BLNO");
    expect(out).toContain("Not set");
    expect(out).toContain("coming later");
  });

  it("shows the configured sender name and reply-to", () => {
    const out = html({
      display_name: "BLNO",
      email_sender_name: "BLNO Coaches",
      email_reply_to: "hi@blno.test",
    });
    expect(out).toContain("BLNO Coaches");
    expect(out).toContain("hi@blno.test");
  });

  it("shows the support email as the reply-to fallback", () => {
    const out = html({
      display_name: "BLNO",
      email_reply_to: null,
      effective_reply_to: "help@blno.test",
      effective_reply_to_source: "support_email",
    });
    expect(out).toContain("help@blno.test (support email)");
    expect(out).not.toContain("Not set");
  });

  it("does not label an explicit reply-to as the support email", () => {
    const out = html({
      display_name: "BLNO",
      email_reply_to: "hi@blno.test",
      effective_reply_to: "hi@blno.test",
      effective_reply_to_source: "reply_to",
    });
    expect(out).toContain("hi@blno.test");
    expect(out).not.toContain("(support email)");
  });
});
