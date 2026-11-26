import { renderToStaticMarkup } from "react-dom/server";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { describe, expect, it, vi } from "vitest";

vi.mock("@/lib/api/v2/messages", () => ({ sendParentMessage: vi.fn() }));

import type { InboxMessage } from "@/lib/api/v2/messages";
import {
  ACADEMY_MESSAGE_MAX,
  AcademyThread,
  THREAD_PAGE,
  composerState,
  sendErrorText,
  threadMessages,
} from "./academy-thread";

function msg(id: string, at: string, extra: Partial<InboxMessage> = {}): InboxMessage {
  return {
    message_id: id,
    kind: "dm",
    sender_persona: "parent",
    body: `body ${id}`,
    created_at: at,
    read: true,
    ...extra,
  };
}

function render(messages: InboxMessage[], phone: string | null = "(309) 555-0142") {
  return renderToStaticMarkup(
    <QueryClientProvider client={new QueryClient()}>
      <AcademyThread
        messages={messages}
        isLoading={false}
        academyName="Demo Academy"
        academyPhone={phone}
        academyTimezone="America/Chicago"
        queryKey={["parent", "messages"]}
      />
    </QueryClientProvider>,
  );
}

describe("threadMessages", () => {
  it("keeps direct messages only, oldest first", () => {
    const out = threadMessages([
      msg("b", "2026-11-26T14:15:00Z"),
      msg("ann", "2026-11-26T13:00:00Z", { kind: "announcement" }),
      msg("a", "2026-11-26T14:02:00Z"),
    ]);
    expect(out.map((m) => m.message_id)).toEqual(["a", "b"]);
  });
});

describe("composerState", () => {
  it("disables Send for blank and over-long text", () => {
    expect(composerState("   ").canSend).toBe(false);
    expect(composerState("x".repeat(ACADEMY_MESSAGE_MAX)).canSend).toBe(true);
    const over = composerState("x".repeat(ACADEMY_MESSAGE_MAX + 1));
    expect(over).toEqual({ count: 1001, tooLong: true, canSend: false });
  });
});

describe("sendErrorText", () => {
  it("names the wait and the phone on a 429", () => {
    expect(sendErrorText({ status: 429 }, "(309) 555-0142")).toBe(
      "You have sent a lot of messages in a short time. Please wait a little, or call (309) 555-0142.",
    );
    expect(sendErrorText({ status: 429 }, null)).not.toContain("call");
  });

  it("says the message was not sent on any other failure", () => {
    expect(sendErrorText(new Error("offline"), "x")).toBe(
      "Your message was not sent. Check your connection and try again.",
    );
  });
});

describe("AcademyThread", () => {
  it("shows the intro with a tappable phone and the empty copy", () => {
    const out = render([]);
    expect(out).toContain("Message the academy");
    expect(out).toContain('href="tel:(309) 555-0142"');
    expect(out).toContain("Your message and the reply stay here.");
    expect(out).toContain("0 / 1000");
  });

  it("drops the urgent-call sentence when the academy has no phone", () => {
    expect(render([], null)).not.toContain("For anything urgent today");
  });

  it("puts my message under You and a reply under the academy, never a staff name", () => {
    const out = render([
      msg("mine", "2026-11-26T14:02:00Z", { mine: true, body: "Sam will be 10 minutes late." }),
      msg("reply", "2026-11-26T14:15:00Z", {
        sender_persona: "admin",
        body: "Thanks, we'll tell the coach.",
        author_display_name: "Marcus",
      }),
    ]);
    expect(out).toContain('aria-label="Messages with Demo Academy"');
    expect(out).toMatch(/data-mine="true"[^]*Sam will be 10 minutes late\./);
    expect(out).toContain("Demo Academy · ");
    expect(out).not.toContain("Marcus");
  });

  it("shows the newest page and offers earlier messages", () => {
    const many = Array.from({ length: THREAD_PAGE + 2 }, (_, i) =>
      msg(`m${i}`, new Date(Date.UTC(2026, 10, 1, 0, i)).toISOString()),
    );
    const out = render(many);
    expect(out).toContain("Show earlier messages");
    expect(out).not.toContain("body m0<");
    expect(out).toContain(`body m${THREAD_PAGE + 1}<`);
  });
});
