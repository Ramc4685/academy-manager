import { beforeEach, describe, expect, it } from "vitest";

import { captureReferralCode, storedReferralCode } from "./referral-capture";

describe("referral capture", () => {
  beforeEach(() => {
    const store = new Map<string, string>();
    Object.defineProperty(globalThis, "window", {
      configurable: true,
      value: {
        localStorage: {
          getItem: (k: string) => store.get(k) ?? null,
          setItem: (k: string, v: string) => void store.set(k, v),
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

  it("drops the code quietly when storage is blocked", () => {
    Object.defineProperty(globalThis, "window", {
      configurable: true,
      value: {
        localStorage: {
          getItem: () => {
            throw new Error("blocked");
          },
          setItem: () => {
            throw new Error("blocked");
          },
        },
      },
    });
    expect(() => captureReferralCode("?ref=QZ7KX4MP")).not.toThrow();
    expect(storedReferralCode()).toBe("");
  });
});
