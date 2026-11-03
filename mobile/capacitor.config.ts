import type { CapacitorConfig } from "@capacitor/cli";

// Spike: the shell loads the deployed Next.js app instead of bundling it,
// because the frontend renders on the server (OpenNext on Workers).
// MOBILE_SERVER_URL picks the target at `cap sync`; default is the local dev
// server (iOS simulator shares the Mac's localhost; Android: `adb reverse tcp:3001 tcp:3001`).
const serverUrl = process.env.MOBILE_SERVER_URL ?? "http://localhost:3001";
// Store builds set MOBILE_RELEASE=1 so a forgotten MOBILE_SERVER_URL fails the sync
// instead of shipping an app pointed at localhost over cleartext.
if (process.env.MOBILE_RELEASE === "1" && !serverUrl.startsWith("https://")) {
  throw new Error(`MOBILE_RELEASE builds need an https MOBILE_SERVER_URL, got ${serverUrl}`);
}
// server.url stays the bare origin: iOS treats any full-page load whose URL does not
// start with server.url as external and opens it in Safari (sign-out did exactly that
// when the path lived here).
const origin = new URL(serverUrl).origin;

const config: CapacitorConfig = {
  appId: "com.courtmastr.academy",
  appName: "Academy",
  webDir: "www",
  // Matches the manifest theme so launch and overscroll never flash white.
  backgroundColor: "#0a0a0a",
  server: {
    url: origin,
    // Not `/` (the marketing landing on the product host): /post-login sends signed-in
    // users to their home and everyone else to /login.
    // iOS refuses to start unless www/post-login exists locally, even though the
    // page itself comes from the server; www/post-login/ is that placeholder.
    appStartPath: "/post-login",
    cleartext: serverUrl.startsWith("http://"),
    // Hosts not listed here open in the system browser, which would strand
    // Stripe Checkout's success_url outside the app.
    // Exact hosts only: every allowed host gets the native bridge. Sign-in runs natively.
    allowNavigation: ["checkout.stripe.com"],
  },
  plugins: {
    // The web Firebase SDK owns the session; the native SDKs only collect the
    // Google/Apple token (frontend/lib/auth/native-sign-in.ts).
    FirebaseAuthentication: {
      skipNativeAuth: true,
      providers: ["google.com", "apple.com"],
    },
  },
  ios: {
    // Service workers in WKWebView need App-Bound Domains (WKAppBoundDomains in Info.plist).
    limitsNavigationsToAppBoundDomains: true,
  },
  // Both Capawesome Firebase plugins' READMEs require this to avoid a SwiftPM
  // package identity collision (capawesome-team/capacitor-firebase#959).
  experimental: {
    ios: {
      spm: {
        packageOptions: {
          "@capacitor-firebase/authentication": { symlink: true },
          "@capacitor-firebase/messaging": { symlink: true },
        },
      },
    },
  },
};

export default config;
