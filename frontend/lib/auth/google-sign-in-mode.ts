export interface GoogleSignInBrowser {
  userAgent: string;
  maxTouchPoints: number;
  platform: string;
}

export function shouldUseRedirectForGoogleSignIn(
  browser: GoogleSignInBrowser
): boolean {
  const userAgent = browser.userAgent.toLowerCase();
  const platform = browser.platform.toLowerCase();

  if (
    /android|webos|iphone|ipad|ipod|blackberry|iemobile|opera mini|mobile/.test(
      userAgent
    )
  ) {
    return true;
  }

  return platform === "macintel" && browser.maxTouchPoints > 1;
}

interface AppShellWindow {
  Capacitor?: { isNativePlatform?: () => boolean };
}

/**
 * True inside the iOS/Android app shell (mobile/), which injects window.Capacitor.
 * Web Google sign-in cannot work there: the redirect to accounts.google.com opens
 * in Safari and returns without the state it started with, so the app hides Google
 * until the native sign-in path ships.
 */
export function isNativeAppShell(win: object | undefined): boolean {
  return (win as AppShellWindow | undefined)?.Capacitor?.isNativePlatform?.() === true;
}
