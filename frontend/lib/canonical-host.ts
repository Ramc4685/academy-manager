export const CANONICAL_HOST_REDIRECTS: Record<string, string> = {
  "acamedy.courtmastr.com": "academy.courtmastr.com",
};

export function canonicalizeRequestUrl(url: URL): URL | null {
  const canonicalHost = CANONICAL_HOST_REDIRECTS[url.hostname.toLowerCase()];
  if (!canonicalHost) return null;

  const redirected = new URL(url.toString());
  redirected.hostname = canonicalHost;
  return redirected;
}
