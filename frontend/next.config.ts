import type { NextConfig } from "next";
import withSerwistInit from "@serwist/next";

import { CANONICAL_HOST_REDIRECTS } from "./lib/canonical-host";

const withSerwist = withSerwistInit({
  swSrc: "app/sw.ts",
  swDest: "public/sw.js",
  cacheOnNavigation: true,
  reloadOnOnline: false,
  disable: process.env.NODE_ENV === "development",
});

// Firebase sign-in helper origin, proxied below so the OAuth round-trip can
// stay first-party on every tenant domain (see lib/auth/auth-domain.ts).
const FIREBASE_AUTH_HELPER_ORIGIN = `https://${
  process.env.NEXT_PUBLIC_FIREBASE_PROJECT_ID ?? "academy-courtmastr"
}.firebaseapp.com`;

const config: NextConfig = {
  reactStrictMode: true,
  poweredByHeader: false,
  typedRoutes: true,
  images: {
    formats: ["image/avif", "image/webp"],
    remotePatterns: [
      { protocol: "https", hostname: "firebasestorage.googleapis.com" },
    ],
  },
  async headers() {
    return [
      {
        source: "/(.*)",
        headers: [
          { key: "X-Content-Type-Options", value: "nosniff" },
          { key: "X-Frame-Options", value: "DENY" },
          { key: "Referrer-Policy", value: "strict-origin-when-cross-origin" },
          { key: "Permissions-Policy", value: "camera=(), microphone=(), geolocation=()" },
          { key: "Cross-Origin-Opener-Policy", value: "same-origin-allow-popups" },
        ],
      },
      {
        // The Firebase auth helper iframe (/__/auth/iframe) must be
        // embeddable by our own pages; the catch-all DENY above would
        // block it. Later rules win for duplicate keys.
        source: "/__/auth/:path*",
        headers: [{ key: "X-Frame-Options", value: "SAMEORIGIN" }],
      },
    ];
  },
  async rewrites() {
    return [
      {
        // Serve the Firebase sign-in helper from every tenant domain so
        // Google sign-in is first-party end-to-end (mobile browsers block
        // the cross-site firebaseapp.com storage that popup/redirect flows
        // otherwise depend on). Used when NEXT_PUBLIC_FIREBASE_AUTH_PROXY=1
        // points authDomain at the page's own host; harmless otherwise.
        source: "/__/auth/:path*",
        destination: `${FIREBASE_AUTH_HELPER_ORIGIN}/__/auth/:path*`,
      },
    ];
  },
  async redirects() {
    return Object.entries(CANONICAL_HOST_REDIRECTS).map(([sourceHost, destinationHost]) => ({
      source: "/:path*",
      has: [{ type: "host" as const, value: sourceHost }],
      destination: `https://${destinationHost}/:path*`,
      permanent: true,
    }));
  },
};

export default withSerwist(config);
