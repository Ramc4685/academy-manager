import { afterEach, describe, expect, it } from "vitest";

import { isNativeApp } from "@/lib/use-native-app";

function installShell(platform: string) {
  (globalThis as { window?: unknown }).window = {
    Capacitor: { isNativePlatform: () => platform !== "web", getPlatform: () => platform },
  };
}

afterEach(() => {
  delete (globalThis as { window?: unknown }).window;
});

describe("isNativeApp", () => {
  it("is false on the server and in a plain browser", () => {
    expect(isNativeApp()).toBe(false);
    installShell("web");
    expect(isNativeApp()).toBe(false);
  });

  it("is true inside the iOS and Android shells", () => {
    installShell("ios");
    expect(isNativeApp()).toBe(true);
    installShell("android");
    expect(isNativeApp()).toBe(true);
  });
});
