import { describe, expect, it } from "vitest";

import { INBOX_TABS, defaultInboxTab, inboxBadge, isInboxTab } from "./admin-inbox-tabs";

describe("defaultInboxTab", () => {
  it("opens the first queue that actually has work", () => {
    expect(defaultInboxTab(null, { registrations: 0, waitlist: 0, "level-ups": 3 })).toBe(
      "level-ups",
    );
  });

  it("honours an explicit tab even when that queue is empty", () => {
    expect(defaultInboxTab("pauses", { registrations: 4, pauses: 0 })).toBe("pauses");
  });

  it("falls back to the first tab when every queue is clear", () => {
    expect(defaultInboxTab(null, { registrations: 0, pauses: 0 })).toBe("registrations");
  });

  it("falls back to the first tab before the counts have loaded", () => {
    expect(defaultInboxTab(null, undefined)).toBe("registrations");
  });

  it("ignores an unknown tab rather than rendering nothing", () => {
    expect(isInboxTab("not-a-queue")).toBe(false);
    expect(defaultInboxTab("not-a-queue", { makeups: 2 })).toBe("makeups");
  });

  it("covers all nine queues, attendance last", () => {
    expect(INBOX_TABS).toHaveLength(9);
    expect(INBOX_TABS.at(-1)).toEqual({ id: "attendance", label: "Attendance" });
  });

  it("lands on Attendance from the dashboard link and when it is the only work", () => {
    expect(defaultInboxTab("attendance", { registrations: 2 })).toBe("attendance");
    expect(defaultInboxTab(null, { registrations: 0, pauses: 0, attendance: 3 })).toBe(
      "attendance",
    );
  });
});

describe("inboxBadge", () => {
  it("never shows a plain number that under-counts", () => {
    expect(inboxBadge(3, false)).toBe(3);
    expect(inboxBadge(0, false)).toBeUndefined();
    expect(inboxBadge(3, true)).toBe("3+");
    expect(inboxBadge(0, true)).toBe("?");
  });
});
