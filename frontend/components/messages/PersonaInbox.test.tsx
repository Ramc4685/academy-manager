import { renderToStaticMarkup } from "react-dom/server";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { describe, expect, it, vi } from "vitest";


import type { InboxMessage } from "@/lib/api/v2/messages";
import { PersonaInbox } from "./PersonaInbox";

const KEY = ["test", "inbox"] as const;

function msg(id: string, kind: InboxMessage["kind"]): InboxMessage {
  return {
    message_id: id,
    kind,
    sender_persona: "admin",
    body: `body ${id}`,
    created_at: "2026-11-26T14:00:00Z",
    read: true,
  };
}

function html(messages: InboxMessage[], excludeDirect: boolean) {
  const client = new QueryClient();
  client.setQueryData(KEY, { messages });
  return renderToStaticMarkup(
    <QueryClientProvider client={client}>
      <PersonaInbox
        queryKey={KEY}
        listMessages={vi.fn()}
        markMessageRead={vi.fn()}
        testId="t"
        emptyStateTitle="No announcements yet."
        emptyStateDescription="desc"
        excludeDirect={excludeDirect}
        renderThread={({ messages: all }) => <div data-testid="slot">{all.length} in thread</div>}
      />
    </QueryClientProvider>,
  );
}

describe("PersonaInbox", () => {
  it("renders the thread slot with every message and lists only announcements", () => {
    const out = html([msg("d1", "dm"), msg("a1", "announcement")], true);
    expect(out).toContain("2 in thread");
    expect(out).toContain("body a1");
    expect(out).not.toContain("body d1");
  });

  it("shows the empty state when only direct messages exist", () => {
    const out = html([msg("d1", "dm")], true);
    expect(out).toContain("No announcements yet.");
  });

  it("keeps direct messages in the list without the flag (coach inbox)", () => {
    expect(html([msg("d1", "dm")], false)).toContain("body d1");
  });
});
