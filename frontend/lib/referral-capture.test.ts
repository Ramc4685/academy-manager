import { beforeEach, describe, expect, it } from "vitest";

import {
  REFERRAL_CODE_MAX_AGE_MS,
  captureReferralCode,
  clearReferralCode,
  storedReferralCode,
} from "./referral-capture";

describe("referral capture", () => {
  let store: Map<string, string>;
  beforeEach(() => {
    store = new Map<string, string>();
    Object.defineProperty(globalThis, "window", {
      configurable: true,
      value: {
        localStorage: {
          getItem: (k: string) => store.get(k) ?? null,
          setItem: (k: string, v: string) => void store.set(k, v),
          removeItem: (k: string) => void store.delete(k),
        },
      },
    });
  });

  it("keeps a valid ?ref= until sign-up reads it, and ignores a bad one", () => {
    expect(storedReferralCode()).toBe("");
    captureReferralCode("?utm_source=x&ref=QZ7KX4MP");
    expect(storedReferralCode()).toBe("QZ7KX4MP");
    captureReferralCode("?ref=bad%20code!");
    captureReferralCode("?class=c1");
    expect(storedReferralCode()).toBe("QZ7KX4MP");
  });

  it("ignores a code captured more than 30 days ago", () => {
    const t0 = Date.UTC(2026, 10, 1);
    captureReferralCode("?ref=QZ7KX4MP", t0);
    expect(storedReferralCode(t0 + REFERRAL_CODE_MAX_AGE_MS - 1)).toBe("QZ7KX4MP");
    expect(storedReferralCode(t0 + REFERRAL_CODE_MAX_AGE_MS)).toBe("");
  });

  it("ignores a bare code left by the earlier format", () => {
    store.set("courtmastr.referral_code", "QZ7KX4MP");
    expect(storedReferralCode()).toBe("");
  });

  it("forgets the code once cleared", () => {
    captureReferralCode("?ref=QZ7KX4MP");
    clearReferralCode();
    expect(storedReferralCode()).toBe("");
    expect(store.size).toBe(0);
  });

  it("drops the code quietly when storage is blocked", () => {
    const blocked = () => {
      throw new Error("blocked");
    };
    Object.defineProperty(globalThis, "window", {
      configurable: true,
      value: { localStorage: { getItem: blocked, setItem: blocked, removeItem: blocked } },
    });
    expect(() => captureReferralCode("?ref=QZ7KX4MP")).not.toThrow();
    expect(() => clearReferralCode()).not.toThrow();
    expect(storedReferralCode()).toBe("");
  });
});
