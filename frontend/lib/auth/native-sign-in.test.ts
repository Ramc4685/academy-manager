import { afterEach, describe, expect, it } from "vitest";

import {
  canUseNativeSignIn,
  nativePlatform,
  shouldOfferAppleSignIn,
  shouldOfferGoogleSignIn,
  toFirebaseCredential,
} from "@/lib/auth/native-sign-in";

function installShell(
  platform: string,
  plugins: string[] = ["FirebaseAuthentication"],
  userAgent = "Mozilla/5.0 (iPhone) AppleWebKit/605.1.15 CourtMastrNativeAuth/1"
) {
  (globalThis as { window?: unknown }).window = {
    navigator: { userAgent },
    Capacitor: {
      isNativePlatform: () => platform !== "web",
      getPlatform: () => platform,
      isPluginAvailable: (name: string) => plugins.includes(name),
    },
  };
}

afterEach(() => {
  delete (globalThis as { window?: unknown }).window;
});

describe("native shell detection", () => {
  it("is off during server rendering", () => {
    expect(nativePlatform()).toBeNull();
    expect(canUseNativeSignIn()).toBe(false);
  });

  it("is off in a normal browser", () => {
    (globalThis as { window?: unknown }).window = {};
    expect(nativePlatform()).toBeNull();
    expect(canUseNativeSignIn()).toBe(false);
    expect(shouldOfferAppleSignIn()).toBe(false);
  });

  it("is off when Capacitor reports the web platform", () => {
    installShell("web");
    expect(canUseNativeSignIn()).toBe(false);
  });

  it("uses native sign-in in the iOS app and offers Apple", () => {
    installShell("ios");
    expect(nativePlatform()).toBe("ios");
    expect(canUseNativeSignIn()).toBe(true);
    expect(shouldOfferAppleSignIn()).toBe(true);
  });

  it("uses native Google sign-in on Android without offering Apple", () => {
    installShell("android");
    expect(canUseNativeSignIn()).toBe(true);
    expect(shouldOfferAppleSignIn()).toBe(false);
  });

  it("falls back to the web flow in an app build without the auth plugin", () => {
    installShell("ios", []);
    expect(canUseNativeSignIn()).toBe(false);
    expect(shouldOfferAppleSignIn()).toBe(false);
  });

  it("hides Google and Apple in an app build without its Firebase config", () => {
    installShell("ios", ["FirebaseAuthentication"], "Mozilla/5.0 (iPhone) AppleWebKit/605.1.15");
    expect(canUseNativeSignIn()).toBe(false);
    expect(shouldOfferGoogleSignIn()).toBe(false);
    expect(shouldOfferAppleSignIn()).toBe(false);
  });

  it("hides Google only in an app build that can't sign in natively", () => {
    (globalThis as { window?: unknown }).window = {};
    expect(shouldOfferGoogleSignIn()).toBe(true);
    installShell("android");
    expect(shouldOfferGoogleSignIn()).toBe(true);
    installShell("android", []);
    expect(shouldOfferGoogleSignIn()).toBe(false);
  });
});

describe("toFirebaseCredential", () => {
  it("maps a Google ID token to a google.com credential", () => {
    const credential = toFirebaseCredential("google", {
      credential: { idToken: "google-id-token", accessToken: "access" },
    });
    expect(credential.providerId).toBe("google.com");
  });

  it("maps an Apple ID token to an apple.com credential", () => {
    const credential = toFirebaseCredential("apple", {
      credential: { idToken: "apple-id-token", nonce: "raw-nonce" },
    });
    expect(credential.providerId).toBe("apple.com");
  });

  it("refuses a result without an ID token", () => {
    expect(() => toFirebaseCredential("apple", { credential: null })).toThrow(
      /Apple sign-in did not return a token/
    );
  });
});
