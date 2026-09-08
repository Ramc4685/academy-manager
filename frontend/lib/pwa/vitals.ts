"use client";

/**
 * Web Vitals reporter.
 *
 * Ships LCP/CLS/INP/FCP/TTFB to Sentry as distribution metrics (only when
 * `NEXT_PUBLIC_SENTRY_DSN` is set — see lib/observability/sentry.ts) and
 * always logs to the console in dev so the perf baseline procedure can
 * read off-screen numbers (see docs/perf-baseline.md, W1A-01).
 */

import type { Metric } from "web-vitals";

import { recordVital } from "@/lib/observability/sentry";

let _started = false;

export function reportVitals(route: string): void {
  if (typeof window === "undefined" || _started) return;
  _started = true;

  void import("web-vitals").then(({ onCLS, onFCP, onINP, onLCP, onTTFB }) => {
    const send = (m: Metric) => {
      const payload = {
        metric: m.name,
        value: m.value,
        rating: m.rating,
        route,
        id: m.id,
      };
      recordVital(m.name, m.value, { rating: m.rating, route, id: m.id });
      if (process.env.NODE_ENV !== "production") {
        // eslint-disable-next-line no-console
        console.log("[vitals]", payload);
      }
    };
    onCLS(send);
    onFCP(send);
    onINP(send);
    onLCP(send);
    onTTFB(send);
  });
}
