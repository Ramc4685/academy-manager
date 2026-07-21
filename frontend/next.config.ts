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

const IS_DEV = process.env.NODE_ENV === "development";

// Report-Only rollout first (QW5): watch for violations in staging/prod, then
// flip the header name to Content-Security-Policy once clean.
// 'unsafe-inline' in script-src is required by the Next.js inline bootstrap
// until nonces are wired. Stripe is hosted-Checkout via a full-page
// `location.href` redirect — a top-level navigation CSP does not restrict —
// so no js.stripe.com script-src or frame-src is needed; form-action lists
// checkout.stripe.com only as defense-in-depth for future <form> posts.
// Cloudflare Web Analytics is auto-injected at the zone level (see the
// beacon.min.js handler in app/sw.ts): its loader needs script-src and its
// RUM POST (cloudflareinsights.com/cdn-cgi/rum) needs connect-src.
// Dev additions: 'unsafe-eval' (React refresh), ws:/localhost (HMR, emulators).
// frame-ancestors is intentionally absent: it is spec-ignored in report-only
// policies (WebKit logs a console error for it) — X-Frame-Options: DENY covers
// framing until enforcement; add `frame-ancestors 'none'` back when flipping.
// report-uri makes the policy observable (WebKit treats a report-only policy
// with no reporting destination as a no-op and logs a console error).
const CONTENT_SECURITY_POLICY = [
  "default-src 'self'",
  `script-src 'self' 'unsafe-inline' https://static.cloudflareinsights.com${IS_DEV ? " 'unsafe-eval'" : ""}`,
  "style-src 'self' 'unsafe-inline'",
  "img-src 'self' data: blob: https://firebasestorage.googleapis.com",
  "font-src 'self' data:",
  `connect-src 'self' https://identitytoolkit.googleapis.com https://securetoken.googleapis.com https://firebasestorage.googleapis.com https://cloudflareinsights.com${
    IS_DEV ? " ws: http://localhost:* http://127.0.0.1:*" : ""
  }`,
  "base-uri 'self'",
  "form-action 'self' https://checkout.stripe.com",
  "object-src 'none'",
  "report-uri /api/csp-report",
].join("; ");

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
          {
            key: "Strict-Transport-Security",
            // No `preload` until all subdomains are confirmed HTTPS-only.
            value: "max-age=31536000; includeSubDomains",
          },
        ],
      },
      {
        // Everything except the proxied Firebase auth helper: that document
        // loads Google's own scripts and must be frameable same-origin, so it
        // stays outside our CSP (mirrors the X-Frame-Options carve-out below).
        source: "/((?!__/auth).*)",
        headers: [
          { key: "Content-Security-Policy-Report-Only", value: CONTENT_SECURITY_POLICY },
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
