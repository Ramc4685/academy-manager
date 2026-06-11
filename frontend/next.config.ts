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
        source: "/__/auth/:path*",
        headers: [{ key: "X-Frame-Options", value: "SAMEORIGIN" }],
      },
    ];
  },
  async rewrites() {
    return [
      {
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
