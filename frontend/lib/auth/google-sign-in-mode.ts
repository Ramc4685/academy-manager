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
