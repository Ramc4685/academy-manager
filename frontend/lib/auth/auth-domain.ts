/**
 * Resolve the Firebase `authDomain` for the current page.
 *
 * Default: the configured NEXT_PUBLIC_FIREBASE_AUTH_DOMAIN
 * (academy-courtmastr.firebaseapp.com). That origin is cross-site from the
 * tenant domains (*.courtmastr.com), and mobile browsers partition or block
 * third-party storage, which breaks BOTH signInWithPopup and
 * signInWithRedirect there — the redirect completes at Google but
 * getRedirectResult() comes back null and the user lands on /login again.
 *
 * Proxy mode (NEXT_PUBLIC_FIREBASE_AUTH_PROXY=1): use the page's own host as
 * authDomain so the whole OAuth round-trip is first-party. next.config.ts
 * rewrites /__/auth/* to the firebaseapp.com sign-in helper. Before enabling
 * in production, each serving domain's https://<host>/__/auth/handler must be
 * added to the Google OAuth client's authorized redirect URIs — see
 * DEPLOYMENT.md "Mobile Google sign-in".
 *
 * Localhost is excluded from proxy mode: the Firebase SDK always builds
 * https://<authDomain>/... URLs, which cannot work against the http dev
 * server, and the firebaseapp.com helper works fine from localhost anyway.
 */
export interface AuthDomainInputs {
  /** NEXT_PUBLIC_FIREBASE_AUTH_DOMAIN as configured at build time. */
  configuredAuthDomain: string | undefined;
  /** NEXT_PUBLIC_FIREBASE_AUTH_PROXY === "1". */
  proxyEnabled: boolean;
  /** window.location.host (host[:port]); undefined during SSR. */
  pageHost: string | undefined;
}

export function resolveAuthDomain(inputs: AuthDomainInputs): string | undefined {
  const { configuredAuthDomain, proxyEnabled, pageHost } = inputs;
  if (!proxyEnabled || !pageHost) return configuredAuthDomain;
  const hostname = pageHost.split(":")[0];
  if (hostname === "localhost" || hostname === "127.0.0.1") {
    return configuredAuthDomain;
  }
  return pageHost;
}
