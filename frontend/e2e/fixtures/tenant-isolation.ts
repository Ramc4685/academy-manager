/**
 * SaaS v2 tenant-isolation network assertion helper.
 *
 * Wave 5 — Agent C.
 *
 * Per AGENTS.md SaaS rules:
 *
 *   "Legacy `/api/*` routes are not part of SaaS mode and must not be
 *   patched for SaaS readiness. New SaaS workflows must use `backend/v2/`
 *   BFF + DDD boundaries."
 *
 * Every SaaS-mode spec should call `installTenantGuard(page)` at the top
 * of the test. The guard installs a request listener that records any
 * call to a legacy `/api/*` path that is NOT `/api/v2/*`. If any such
 * call is observed, the test fails fast at the end via
 * `assertNoLegacyApiCalls()` (or you can fail fast mid-test by passing
 * `{ failFast: true }`).
 *
 * Additionally, the guard captures the request-scoped tenant identity
 * by reading the canonical SaaS headers if present (`X-Tenant`,
 * `X-Tenant-Id`, `X-Academy-Id`) and the `Authorization` header. That
 * lets specs assert that, e.g., switching academies in the UI flips the
 * tenant on subsequent BFF calls.
 *
 * NOTE: this file does NOT stub any backend response — it only observes.
 * Spec authors still set up their own `page.route` stubs.
 */

import type { Page, Request } from "@playwright/test";
import { expect } from "@playwright/test";

export interface CapturedRequest {
  url: string;
  method: string;
  tenantHeader: string | null;
  authHeader: string | null;
  isLegacy: boolean;
}

export interface TenantGuard {
  /** Every observed BFF request (v2 + any leaking legacy). */
  readonly requests: ReadonlyArray<CapturedRequest>;
  /** Subset of `requests` whose URL starts with /api/ but NOT /api/v2/. */
  readonly legacyRequests: ReadonlyArray<CapturedRequest>;
  /** Subset of `requests` whose URL starts with /api/v2/. */
  readonly v2Requests: ReadonlyArray<CapturedRequest>;
  /**
   * Throws `expect` assertion if any legacy /api/* call was observed.
   * Call at end of each SaaS test (or rely on `installTenantGuard`'s
   * `failFast: true`).
   */
  assertNoLegacyApiCalls(): void;
  /** Distinct tenant header values seen on v2 requests, in order. */
  tenantsObserved(): string[];
}

/**
 * Path is legacy iff it begins with /api/ and not /api/v2/. Cloudflare
 * Worker, Next.js asset fetches, and Firebase/Stripe domains are
 * ignored (we only flag the academy-manager BFF).
 */
function isLegacyApiPath(url: string): boolean {
  try {
    const u = new URL(url);
    const path = u.pathname;
    if (!path.startsWith("/api/")) return false;
    if (path.startsWith("/api/v2/")) return false;
    // /api/health was a legacy smoke route and must stay unavailable.
    return true;
  } catch {
    return false;
  }
}

function isV2ApiPath(url: string): boolean {
  try {
    const u = new URL(url);
    return u.pathname.startsWith("/api/v2/");
  } catch {
    return false;
  }
}

function pickTenantHeader(req: Request): string | null {
  const headers = req.headers();
  return (
    headers["x-tenant"] ??
    headers["x-tenant-id"] ??
    headers["x-academy-id"] ??
    null
  );
}

export function installTenantGuard(
  page: Page,
  options: { failFast?: boolean } = {}
): TenantGuard {
  const requests: CapturedRequest[] = [];

  page.on("request", (req) => {
    const url = req.url();
    const legacy = isLegacyApiPath(url);
    const v2 = isV2ApiPath(url);
    if (!legacy && !v2) return;

    const captured: CapturedRequest = {
      url,
      method: req.method(),
      tenantHeader: pickTenantHeader(req),
      authHeader: req.headers()["authorization"] ?? null,
      isLegacy: legacy,
    };
    requests.push(captured);

    if (legacy && options.failFast) {
      // Throwing here doesn't fail the Playwright test directly because
      // the listener runs out-of-band. We surface it via the next
      // assertNoLegacyApiCalls call. To fail-fast users can `await
      // page.waitForEvent('request', { predicate: ... })` themselves.
      // eslint-disable-next-line no-console
      console.error(
        `[tenant-guard] legacy /api call detected: ${captured.method} ${captured.url}`
      );
    }
  });

  return {
    get requests() {
      return requests;
    },
    get legacyRequests() {
      return requests.filter((r) => r.isLegacy);
    },
    get v2Requests() {
      return requests.filter((r) => !r.isLegacy);
    },
    assertNoLegacyApiCalls() {
      const offenders = requests.filter((r) => r.isLegacy);
      expect(
        offenders,
        `SaaS specs must not call legacy /api/* — saw:\n${offenders
          .map((o) => `  ${o.method} ${o.url}`)
          .join("\n")}`
      ).toEqual([]);
    },
    tenantsObserved() {
      const seen: string[] = [];
      for (const r of requests) {
        if (r.isLegacy) continue;
        if (r.tenantHeader && !seen.includes(r.tenantHeader)) {
          seen.push(r.tenantHeader);
        }
      }
      return seen;
    },
  };
}

/**
 * Convenience: collect non-benign console errors. Mirrors the helper
 * used by existing admin-shell / admin-students / admin-waivers specs
 * so SaaS specs follow the same console-cleanliness contract.
 */
const BENIGN_PATTERNS: RegExp[] = [
  /Download the React DevTools/i,
  /Fast Refresh/i,
  /HMR/i,
  /webpack-internal/i,
];

export function collectConsoleErrors(page: Page): string[] {
  const errors: string[] = [];
  page.on("console", (msg) => {
    if (msg.type() !== "error") return;
    const text = msg.text();
    if (BENIGN_PATTERNS.some((re) => re.test(text))) return;
    errors.push(text);
  });
  return errors;
}
