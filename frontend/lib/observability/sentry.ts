/**
 * Browser error capture (audit C2, frontend half).
 *
 * Everything here is gated on `NEXT_PUBLIC_SENTRY_DSN`: with the DSN unset
 * `initSentry()` and `captureError()` are no-ops and `@sentry/browser` is never
 * loaded — the import is dynamic, so the SDK costs nothing in the bundle until
 * an environment actually opts in.
 *
 * The backend already reports to Sentry with `X-Request-ID` as a tag; the same
 * id is minted/echoed by the BFF proxy and lands on `ApiError.requestId`, so a
 * client-side capture of an API failure can be joined to its server event.
 */

import type * as SentryModule from "@sentry/browser";

type Sentry = typeof SentryModule;

export interface CaptureContext {
  /** Next.js error digest from `error.tsx` / `global-error.tsx`. */
  digest?: string;
  /** Free-form tags; values are stringified. */
  tags?: Record<string, string | number | boolean | undefined>;
  /** Extra structured context (never PII). */
  extra?: Record<string, unknown>;
}

let sdk: Promise<Sentry | null> | null = null;

/**
 * Drop the query string (and fragment) from a URL. The app carries live
 * credentials and PII in query strings — `/auth/magic?t=<login token>`,
 * `/auth/action?oobCode=<password-reset code>`, `/unsubscribe?t=<token>`,
 * `/login?email=<address>` — and the SDK's default integrations would ship
 * them on every event: `httpContextIntegration` stamps `event.request.url`
 * with `location.href`, and navigation/fetch breadcrumbs keep the full
 * relative URL. `sendDefaultPii: false` does not touch either, so the scrub
 * lives here (the backend's request-id validation is the server-side twin).
 */
export function stripQuery(url: string): string {
  const cut = url.search(/[?#]/);
  return cut === -1 ? url : url.slice(0, cut);
}

type SentryEvent = Parameters<NonNullable<SentryModule.BrowserOptions["beforeSend"]>>[0];
type SentryBreadcrumb = Parameters<
  NonNullable<SentryModule.BrowserOptions["beforeBreadcrumb"]>
>[0];

/** `beforeSend`: scrub the page URL and the Referer header on every event. */
export function scrubEventUrls<T extends SentryEvent>(event: T): T {
  if (event.request?.url) event.request.url = stripQuery(event.request.url);
  const headers = event.request?.headers;
  if (headers?.Referer) headers.Referer = stripQuery(headers.Referer);
  return event;
}

/** `beforeBreadcrumb`: scrub navigation `from`/`to` and fetch/xhr `url`. */
export function scrubBreadcrumbUrls<T extends SentryBreadcrumb>(breadcrumb: T): T {
  const data = breadcrumb.data;
  if (!data) return breadcrumb;
  for (const key of ["from", "to", "url"] as const) {
    if (typeof data[key] === "string") data[key] = stripQuery(data[key]);
  }
  return breadcrumb;
}

export function sentryDsn(): string | null {
  const dsn = process.env.NEXT_PUBLIC_SENTRY_DSN?.trim();
  return dsn ? dsn : null;
}

/** True when a DSN is configured; nothing is loaded until `initSentry()` runs. */
export function isSentryEnabled(): boolean {
  return sentryDsn() !== null;
}

/**
 * Initialise the browser SDK once. Safe to call repeatedly and on the server
 * (no-op there). Resolves to the loaded module, or null when disabled.
 */
export function initSentry(): Promise<Sentry | null> {
  if (sdk) return sdk;
  const dsn = sentryDsn();
  // Never load under browser automation (Playwright sets navigator.webdriver):
  // e2e runs must not post envelopes to the real project, and the e2e
  // tenant-isolation fixture treats any stray network call as a failure.
  const automated = typeof navigator !== "undefined" && navigator.webdriver === true;
  if (!dsn || typeof window === "undefined" || automated) {
    sdk = Promise.resolve(null);
    return sdk;
  }
  sdk = import("@sentry/browser")
    .then((mod) => {
      mod.init({
        dsn,
        environment: process.env.NEXT_PUBLIC_APP_ENV || "production",
        release: process.env.NEXT_PUBLIC_SENTRY_RELEASE || undefined,
        // Errors only: every event, no performance tracing. The SDK default
        // for PII is already off; keep it explicit so a future default flip
        // cannot start shipping IPs/cookies.
        sampleRate: 1,
        tracesSampleRate: 0,
        sendDefaultPii: false,
        // Query strings carry magic-link tokens, Firebase oobCodes and parent
        // emails; strip them before anything leaves the browser.
        beforeSend: scrubEventUrls,
        beforeBreadcrumb: scrubBreadcrumbUrls,
      });
      return mod;
    })
    .catch((loadError: unknown) => {
      // A blocked CDN/CSP or a chunk load failure must never break the app.
      console.error("[observability] Sentry failed to load", loadError);
      return null;
    });
  return sdk;
}

/**
 * Report an error with optional context. No-op unless the DSN is set; never
 * throws. Callers keep their own `console.error` so dev consoles stay useful.
 */
export function captureError(error: unknown, context: CaptureContext = {}): void {
  if (!isSentryEnabled()) return;
  void initSentry().then((mod) => {
    if (!mod) return;
    mod.withScope((scope) => {
      if (context.digest) scope.setTag("next.digest", context.digest);
      for (const [key, value] of Object.entries(context.tags ?? {})) {
        if (value !== undefined) scope.setTag(key, String(value));
      }
      if (context.extra) scope.setContext("extra", context.extra);
      mod.captureException(error);
    });
  });
}

/**
 * Record a Web Vital as a Sentry distribution metric (`Sentry.metrics` is part
 * of @sentry/browser 10.x). No-op unless the DSN is set.
 */
export function recordVital(
  name: string,
  value: number,
  attributes: Record<string, string | number | boolean>
): void {
  if (!isSentryEnabled()) return;
  void initSentry().then((mod) => {
    if (!mod) return;
    mod.metrics.distribution(`web_vitals.${name.toLowerCase()}`, value, {
      unit: name === "CLS" ? "none" : "millisecond",
      attributes,
    });
  });
}

/** Test seam: forget the loaded SDK so env changes are re-read. */
export function resetSentryForTests(): void {
  sdk = null;
}
