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
// Open on login, not `/`: the root route is the marketing landing on the product host.
const startUrl = new URL("/login", serverUrl).toString();

const config: CapacitorConfig = {
  appId: "com.courtmastr.academy",
  appName: "Academy",
  webDir: "www",
  // Matches the manifest theme so launch and overscroll never flash white.
  backgroundColor: "#0a0a0a",
  server: {
    url: startUrl,
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
};

export default config;
