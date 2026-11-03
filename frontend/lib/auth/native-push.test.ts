import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

const apiFetch = vi.fn();
vi.mock("@/lib/api/client", () => ({ apiFetch: (...args: unknown[]) => apiFetch(...args) }));

type Listener = (event: unknown) => void;
const listeners = new Map<string, Listener>();
const plugin = {
  addListener: vi.fn(async (event: string, cb: Listener) => {
    listeners.set(event, cb);
    return { remove: async () => undefined };
  }),
  checkPermissions: vi.fn(async () => ({ receive: "prompt" })),
  requestPermissions: vi.fn(async () => ({ receive: "granted" })),
  register: vi.fn(async () => undefined),
  removeAllListeners: vi.fn(async () => listeners.clear()),
};
vi.mock("@capacitor/push-notifications", () => ({ PushNotifications: plugin }));

async function load() {
  vi.resetModules();
  return import("@/lib/auth/native-push");
}

function installShell(platform: string, plugins: string[] = ["PushNotifications", "PushReady"]) {
  const assign = vi.fn();
  (globalThis as { window?: unknown }).window = {
    Capacitor: {
      isNativePlatform: () => platform !== "web",
      getPlatform: () => platform,
      isPluginAvailable: (name: string) => plugins.includes(name),
    },
    location: { assign },
  };
  return assign;
}

beforeEach(() => {
  apiFetch.mockReset().mockResolvedValue(null);
  listeners.clear();
  vi.clearAllMocks();
});

afterEach(() => {
  delete (globalThis as { window?: unknown }).window;
});

describe("push detection", () => {
  it("is off in browsers and on the server", async () => {
    const push = await load();
    expect(push.canUsePush()).toBe(false);
    (globalThis as { window?: unknown }).window = {};
    expect(push.canUsePush()).toBe(false);
  });

  it("is off in an older shell without the plugin", async () => {
    installShell("ios", ["FirebaseAuthentication"]);
    const push = await load();
    expect(push.canUsePush()).toBe(false);
    await push.startPushNotifications();
    expect(plugin.addListener).not.toHaveBeenCalled();
  });

  it("is on in a shell with the plugin", async () => {
    installShell("android");
    expect((await load()).canUsePush()).toBe(true);
    installShell("ios", ["PushNotifications"]);
    expect((await load()).canUsePush()).toBe(true);
  });

  it("is off on Android until Firebase is configured (register() would crash)", async () => {
    installShell("android", ["PushNotifications"]);
    const push = await load();
    expect(push.canUsePush()).toBe(false);
    await push.startPushNotifications();
    expect(plugin.register).not.toHaveBeenCalled();
  });
});

describe("safeAppPath", () => {
  it.each([
    ["/parent/payments", "/parent/payments"],
    ["/coach/today?session=s_1#roster", "/coach/today?session=s_1#roster"],
  ])("keeps the in-app path %s", async (input, expected) => {
    expect((await load()).safeAppPath(input)).toBe(expected);
  });

  it.each([
    "https://evil.example/phish",
    "//evil.example/phish",
    "/\\evil.example",
    "/\t/evil.example",
    "javascript:alert(1)",
    "parent/payments",
    "",
    undefined,
    42,
  ])("rejects %s", async (input) => {
    expect((await load()).safeAppPath(input)).toBeNull();
  });
});

describe("startPushNotifications", () => {
  it("does nothing in a browser", async () => {
    (globalThis as { window?: unknown }).window = {};
    await (await load()).startPushNotifications();
    expect(plugin.checkPermissions).not.toHaveBeenCalled();
    expect(apiFetch).not.toHaveBeenCalled();
  });

  it("asks once, registers, and posts the token with the platform", async () => {
    installShell("ios");
    const push = await load();
    await push.startPushNotifications();
    await push.startPushNotifications();

    expect(plugin.requestPermissions).toHaveBeenCalledTimes(1);
    expect(plugin.register).toHaveBeenCalledTimes(1);

    listeners.get("registration")!({ value: "tok-123" });
    expect(apiFetch).toHaveBeenCalledWith("/me/devices", {
      method: "POST",
      body: JSON.stringify({ token: "tok-123", platform: "ios" }),
    });
  });

  it("does not re-prompt or register when permission was denied", async () => {
    installShell("android");
    plugin.checkPermissions.mockResolvedValueOnce({ receive: "denied" });
    await (await load()).startPushNotifications();
    expect(plugin.requestPermissions).not.toHaveBeenCalled();
    expect(plugin.register).not.toHaveBeenCalled();
  });

  it("stays quiet when registration or the token upload fails", async () => {
    installShell("android");
    plugin.register.mockRejectedValueOnce(new Error("no google-services.json"));
    apiFetch.mockRejectedValue(new Error("500"));
    const push = await load();
    await expect(push.startPushNotifications()).resolves.toBeUndefined();
    listeners.get("registrationError")!({ error: "missing config" });
    listeners.get("registration")!({ value: "tok" });
    await Promise.resolve();
  });

  it("opens same-origin notification links and ignores external ones", async () => {
    const assign = installShell("ios");
    await (await load()).startPushNotifications();
    const tap = listeners.get("pushNotificationActionPerformed")!;

    tap({ notification: { data: { url: "/parent/messages" } } });
    tap({ notification: { data: { url: "https://evil.example" } } });
    tap({ notification: { data: {} } });

    expect(assign).toHaveBeenCalledTimes(1);
    expect(assign).toHaveBeenCalledWith("/parent/messages");
  });
});

describe("stopPushNotifications", () => {
  it("deletes the registered token and resets so the next user registers", async () => {
    installShell("ios");
    const push = await load();
    await push.startPushNotifications();
    listeners.get("registration")!({ value: "tok/with+chars" });
    apiFetch.mockClear();

    await push.stopPushNotifications();
    expect(apiFetch).toHaveBeenCalledWith("/me/devices/tok%2Fwith%2Bchars", { method: "DELETE" });
    expect(plugin.removeAllListeners).toHaveBeenCalled();

    await push.startPushNotifications();
    expect(plugin.register).toHaveBeenCalledTimes(2);
  });

  it("is a no-op in a browser", async () => {
    await (await load()).stopPushNotifications();
    expect(apiFetch).not.toHaveBeenCalled();
  });

  it("never blocks sign-out on a failing or hanging delete", async () => {
    installShell("android");
    const push = await load();
    await push.startPushNotifications();
    listeners.get("registration")!({ value: "tok" });

    apiFetch.mockRejectedValueOnce(new Error("offline"));
    await expect(push.stopPushNotifications()).resolves.toBeUndefined();

    await push.startPushNotifications();
    listeners.get("registration")!({ value: "tok" });
    vi.useFakeTimers();
    try {
      apiFetch.mockReturnValueOnce(new Promise(() => undefined));
      const stopped = push.stopPushNotifications();
      await vi.advanceTimersByTimeAsync(3_000);
      await expect(stopped).resolves.toBeUndefined();
    } finally {
      vi.useRealTimers();
    }
  });
});
