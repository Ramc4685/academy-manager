import type { CapacitorConfig } from "@capacitor/cli";

// Spike: the shell loads the deployed Next.js app instead of bundling it,
// because the frontend renders on the server (OpenNext on Workers).
// MOBILE_SERVER_URL picks the target at `cap sync`; default is the local dev
// server (iOS simulator reaches the Mac at localhost; Android emulator needs 10.0.2.2).
const serverUrl = process.env.MOBILE_SERVER_URL ?? "http://localhost:3001";
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
