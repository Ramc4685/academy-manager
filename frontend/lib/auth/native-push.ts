/**
 * Push notifications inside the iOS/Android app shell (see mobile/, slice M4).
 *
 * Uses @capacitor-firebase/messaging because the backend sends through FCM and
 * needs FCM registration tokens on iOS too, not raw APNs device tokens.
 *
 * Browsers never reach the plugin: every entry point checks the shell first
 * and the plugin is dynamic-imported, so the web bundle loads no Capacitor
 * code. Push is best-effort; any failure (no Firebase config yet, permission
 * denied, network) is swallowed so it never shows an error or blocks a flow.
 */

import { apiFetch } from "@/lib/api/client";
import { hasNativePlugin, nativePlatform } from "@/lib/auth/native-sign-in";

const PLUGIN = "FirebaseMessaging";
/** Sign-out waits at most this long for the device to be dropped server-side. */
const UNREGISTER_TIMEOUT_MS = 3_000;

/** Survives full page loads, so sign-out can drop a token registered on an earlier page. */
const TOKEN_KEY = "am.pushToken";

let started = false;

function storedToken(): string | null {
  try {
    return window.localStorage.getItem(TOKEN_KEY);
  } catch {
    return null;
  }
}

function storeToken(token: string | null): void {
  try {
    if (token) window.localStorage.setItem(TOKEN_KEY, token);
    else window.localStorage.removeItem(TOKEN_KEY);
  } catch {
    // Storage blocked: sign-out falls back to the backend rebinding the token.
  }
}

export function canUsePush(): boolean {
  // Without google-services.json / GoogleService-Info.plist the plugin still
  // loads and getToken() just rejects, so no Firebase-config check is needed here.
  return hasNativePlugin(PLUGIN);
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
    // "/.//evil.example" normalises to "//evil.example", which assign() reads as a host.
    if (parsed.origin !== base || parsed.pathname.startsWith("//")) return null;
    return `${parsed.pathname}${parsed.search}${parsed.hash}`;
  } catch {
    return null;
  }
}

/**
 * Ask for permission (the OS only prompts once), fetch the FCM registration
 * token and send it to the backend. Safe to call on every signed-in page load.
 */
export async function startPushNotifications(): Promise<void> {
  const platform = nativePlatform();
  if (started || !platform || !canUsePush()) return;
  started = true;
  const save = (token: string) => {
    storeToken(token);
    void apiFetch("/me/devices", {
      method: "POST",
      body: JSON.stringify({ token, platform }),
    }).catch(() => undefined);
  };
  try {
    const { FirebaseMessaging } = await import("@capacitor-firebase/messaging");
    await FirebaseMessaging.addListener("tokenReceived", ({ token }) => save(token));
    await FirebaseMessaging.addListener("notificationActionPerformed", ({ notification }) => {
      const path = safeAppPath((notification.data as { url?: unknown } | undefined)?.url);
      if (path) window.location.assign(path);
    });

    let { receive } = await FirebaseMessaging.checkPermissions();
    if (receive === "prompt" || receive === "prompt-with-rationale") {
      ({ receive } = await FirebaseMessaging.requestPermissions());
    }
    if (receive !== "granted") return;
    // Rejects without Firebase config; the catch below keeps that quiet.
    save((await FirebaseMessaging.getToken()).token);
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
  const token = storedToken();
  if (!started && !token) return;
  started = false;
  storeToken(null);
  // Best-effort: deleteToken() also makes FCM issue a fresh token for the next user.
  const native = import("@capacitor-firebase/messaging")
    .then(async ({ FirebaseMessaging }) => {
      await FirebaseMessaging.removeAllListeners();
      await FirebaseMessaging.deleteToken();
    })
    .catch(() => undefined);
  const request = token
    ? apiFetch(`/me/devices/${encodeURIComponent(token)}`, { method: "DELETE" }).catch(
        () => undefined,
      )
    : undefined;
  await Promise.race([
    Promise.all([native, request]),
    new Promise((resolve) => setTimeout(resolve, UNREGISTER_TIMEOUT_MS)),
  ]);
}
