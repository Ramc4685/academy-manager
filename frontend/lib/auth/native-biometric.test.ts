import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

const plugin = {
  isAvailable: vi.fn(async () => ({ isAvailable: true, deviceIsSecure: true, biometryType: 2 })),
  verifyIdentity: vi.fn(async () => undefined),
};
vi.mock("@capgo/capacitor-native-biometric", () => ({ NativeBiometric: plugin }));

async function load() {
  vi.resetModules();
  return import("@/lib/auth/native-biometric");
}

const store = new Map<string, string>();

function installShell(plugins: string[] = ["NativeBiometric"]) {
  (globalThis as { window?: unknown }).window = {
    Capacitor: {
      isNativePlatform: () => true,
      getPlatform: () => "ios",
      isPluginAvailable: (name: string) => plugins.includes(name),
    },
    localStorage: {
      getItem: (k: string) => store.get(k) ?? null,
      setItem: (k: string, v: string) => void store.set(k, v),
      removeItem: (k: string) => void store.delete(k),
    },
  };
}

beforeEach(() => {
  store.clear();
  vi.clearAllMocks();
});

afterEach(() => {
  delete (globalThis as { window?: unknown }).window;
});

describe("app lock (Face ID / fingerprint)", () => {
  it("is never offered in a browser or an app build without the plugin", async () => {
    const lock = await load();
    expect(await lock.biometricAvailability()).toBeNull();
    installShell([]);
    expect(await lock.biometricAvailability()).toBeNull();
    expect(lock.isBiometricLockOn()).toBe(false);
  });

  it("names the phone's method", async () => {
    installShell();
    const lock = await load();
    expect(await lock.biometricAvailability()).toBe("Face ID");
    expect(lock.biometricLabel(3)).toBe("fingerprint");
    expect(lock.biometricLabel(0)).toBe("your phone's screen lock");
  });

  it("offers nothing on a phone with no face, fingerprint or passcode", async () => {
    installShell();
    plugin.isAvailable.mockResolvedValueOnce({ isAvailable: false, deviceIsSecure: false, biometryType: 0 });
    const lock = await load();
    expect(await lock.biometricAvailability()).toBeNull();
  });

  it("turns on only after the person passes a scan", async () => {
    installShell();
    const lock = await load();
    plugin.verifyIdentity.mockRejectedValueOnce(new Error("cancelled"));
    expect(await lock.enableBiometricLock()).toBe(false);
    expect(lock.isBiometricLockOn()).toBe(false);

    expect(await lock.enableBiometricLock()).toBe(true);
    expect(lock.isBiometricLockOn()).toBe(true);
    expect(plugin.verifyIdentity).toHaveBeenLastCalledWith(
      expect.objectContaining({ useFallback: true }),
    );

    lock.disableBiometricLock();
    expect(lock.isBiometricLockOn()).toBe(false);
  });

  it("reports a failed unlock instead of throwing", async () => {
    installShell();
    plugin.verifyIdentity.mockRejectedValueOnce(new Error("no match"));
    const lock = await load();
    expect(await lock.verifyWithBiometrics("Unlock")).toBe(false);
  });

  it("hides the page before first paint only when the lock is on in the app", async () => {
    installShell();
    const { APP_LOCK_BOOT_SCRIPT } = await import("@/lib/auth/app-lock-key");
    const lock = await load();
    const run = () => {
      const attrs = new Set<string>();
      const win = (globalThis as { window: Record<string, unknown> }).window;
      new Function("window", "localStorage", "document", APP_LOCK_BOOT_SCRIPT)(
        win,
        win.localStorage,
        { documentElement: { setAttribute: (name: string) => attrs.add(name) } },
      );
      return attrs.has("data-app-lock");
    };
    expect(run()).toBe(false);
    await lock.enableBiometricLock();
    expect(run()).toBe(true);
  });
});
