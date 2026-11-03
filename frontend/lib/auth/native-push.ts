/**
 * Push notifications inside the iOS/Android app shell (see mobile/, slice M4).
 *
 * Browsers never reach the plugin: every entry point checks the shell first
 * and the plugin is dynamic-imported, so the web bundle loads no Capacitor
 * code. Push is best-effort; any failure (no Firebase config yet, permission
 * denied, network) is swallowed so it never shows an error or blocks a flow.
 */

import { apiFetch } from "@/lib/api/client";
import { hasNativePlugin, nativePlatform } from "@/lib/auth/native-sign-in";

const PLUGIN = "PushNotifications";
/** Sign-out waits at most this long for the device to be dropped server-side. */
const UNREGISTER_TIMEOUT_MS = 3_000;

let started = false;
let registeredToken: string | null = null;

export function canUsePush(): boolean {
  if (!hasNativePlugin(PLUGIN)) return false;
  // Android's register() crashes the app when Firebase isn't configured; the
  // shell registers the PushReady marker only when google-services.json is bundled.
  return nativePlatform() !== "android" || hasNativePlugin("PushReady");
}

/**
 * The in-app path a notification's `data.url` points at, or null when it is
 * anything other than a same-origin path (absolute URLs, `//host`, schemes).
 */
export function safeAppPath(url: unknown): string | null {
  if (typeof url !== "string" || !url.startsWith("/")) return null;
  const base = "https://app.invalid";
  try {
    // The URL parser also normalises tricks like "/\\evil.com" or tabs.
    const parsed = new URL(url, base);
    if (parsed.origin !== base) return null;
    return `${parsed.pathname}${parsed.search}${parsed.hash}`;
  } catch {
    return null;
  }
}

/**
 * Ask for permission (the OS only prompts once), register with FCM/APNs and
 * send the token to the backend. Safe to call on every signed-in page load.
 */
export async function startPushNotifications(): Promise<void> {
  const platform = nativePlatform();
  if (started || !platform || !canUsePush()) return;
  started = true;
  try {
    const { PushNotifications } = await import("@capacitor/push-notifications");
    await PushNotifications.addListener("registration", ({ value }) => {
      registeredToken = value;
      void apiFetch("/me/devices", {
        method: "POST",
        body: JSON.stringify({ token: value, platform }),
      }).catch(() => undefined);
    });
    // Without GoogleService-Info.plist / google-services.json this fires; stay quiet.
    await PushNotifications.addListener("registrationError", () => undefined);
    await PushNotifications.addListener("pushNotificationActionPerformed", ({ notification }) => {
      const path = safeAppPath((notification.data as { url?: unknown } | undefined)?.url);
      if (path) window.location.assign(path);
    });

    let { receive } = await PushNotifications.checkPermissions();
    if (receive === "prompt" || receive === "prompt-with-rationale") {
      ({ receive } = await PushNotifications.requestPermissions());
    }
    if (receive !== "granted") return;
    await PushNotifications.register();
  } catch {
    // Push is optional; the app works without it.
  }
}

/**
 * Drop this phone's token for the signed-in user before sign-out, so the next
 * person to use the phone doesn't get their pushes. Never throws, never waits
 * longer than UNREGISTER_TIMEOUT_MS.
 */
export async function stopPushNotifications(): Promise<void> {
  if (!started) return;
  const token = registeredToken;
  started = false;
  registeredToken = null;
  try {
    const { PushNotifications } = await import("@capacitor/push-notifications");
    await PushNotifications.removeAllListeners();
  } catch {
    // Listeners die with the page anyway.
  }
  if (!token) return;
  const request = apiFetch(`/me/devices/${encodeURIComponent(token)}`, {
    method: "DELETE",
  }).catch(() => undefined);
  await Promise.race([
    request,
    new Promise((resolve) => setTimeout(resolve, UNREGISTER_TIMEOUT_MS)),
  ]);
}
