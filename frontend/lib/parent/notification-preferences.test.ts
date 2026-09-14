import { describe, expect, it } from "vitest";

import {
  NOTIFICATION_CHANNELS,
  isChannelOn,
  setChannel,
  type ParentEmailPreferences,
} from "./notification-preferences";

const ALL_ON: ParentEmailPreferences = {
  campaigns_opted_out: false,
  digests_opted_out: false,
  notifications_opted_out: false,
};

describe("parent notification preferences", () => {
  it("offers exactly the three switchable channels, most important first", () => {
    expect(NOTIFICATION_CHANNELS.map((channel) => channel.key)).toEqual([
      "notifications",
      "digests",
      "campaigns",
    ]);
    for (const channel of NOTIFICATION_CHANNELS) {
      expect(channel.label.length).toBeGreaterThan(0);
      expect(channel.description.length).toBeGreaterThan(0);
    }
  });

  it("reads a channel as ON when the stored flag is opted-OUT=false", () => {
    expect(isChannelOn(ALL_ON, "notifications")).toBe(true);
    expect(isChannelOn(ALL_ON, "digests")).toBe(true);
    expect(isChannelOn(ALL_ON, "campaigns")).toBe(true);

    const noMarketing: ParentEmailPreferences = { ...ALL_ON, campaigns_opted_out: true };
    expect(isChannelOn(noMarketing, "campaigns")).toBe(false);
    expect(isChannelOn(noMarketing, "digests")).toBe(true);
  });

  it("treats a missing notifications flag as ON (the field is optional on the wire)", () => {
    const legacy = { campaigns_opted_out: false, digests_opted_out: false } as ParentEmailPreferences;
    expect(isChannelOn(legacy, "notifications")).toBe(true);
  });

  it("switching a channel off flips only that channel's opt-out flag", () => {
    const next = setChannel(ALL_ON, "digests", false);
    expect(next).toEqual({
      campaigns_opted_out: false,
      digests_opted_out: true,
      notifications_opted_out: false,
    });
    // immutable: the caller's object is untouched, so React state updates cleanly
    expect(ALL_ON.digests_opted_out).toBe(false);
  });

  it("switching a channel back on clears its opt-out flag", () => {
    const off: ParentEmailPreferences = { ...ALL_ON, notifications_opted_out: true };
    expect(setChannel(off, "notifications", true)).toEqual(ALL_ON);
  });
});
