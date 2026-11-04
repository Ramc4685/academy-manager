/**
 * Host handling for the root route.
 *
 * The public academy page is `/` on a tenant host; the product's own hosts
 * keep the CourtMastr landing page (brief section 4). This list is needed on
 * the frontend because production runs the backend in `single_academy`
 * mode, where every host (the product host included) resolves to the one
 * live academy, so "ask the API" alone cannot tell the product host apart.
 */

export const DEFAULT_PLATFORM_PRODUCT_HOSTS = [
  "academy.courtmastr.com",
  "courtmastr.com",
  "www.courtmastr.com",
] as const;

/** Lower-cased host without the port ("Academy.Example:443" -> "academy.example"). */
export function normalizeHost(host: string | null | undefined): string {
  if (!host) return "";
  const first = host.split(",")[0].trim().toLowerCase();
  if (first.startsWith("[")) {
    // IPv6 literal: keep the bracketed address, drop the port.
    const end = first.indexOf("]");
    return end === -1 ? first : first.slice(0, end + 1);
  }
  return first.replace(/:\d+$/, "").replace(/\.$/, "");
}

/**
 * `PUBLIC_PAGE_PLATFORM_HOSTS` (comma separated) replaces the default list;
 * an empty value means "no platform host" (every host is a tenant host).
 */
type HostEnv = Record<string, string | undefined>;

export function platformProductHosts(env: HostEnv): string[] {
  const raw = env.PUBLIC_PAGE_PLATFORM_HOSTS;
  if (raw === undefined) return [...DEFAULT_PLATFORM_PRODUCT_HOSTS];
  return raw
    .split(",")
    .map((h) => normalizeHost(h))
    .filter(Boolean);
}

export function isPlatformProductHost(
  host: string | null | undefined,
  env: HostEnv,
): boolean {
  const normalized = normalizeHost(host);
  if (!normalized) return false;
  return platformProductHosts(env).includes(normalized);
}

/**
 * `https://<host>` for canonical links, the OG card URL, robots and sitemap.
 * Development servers speak plain http.
 */
export function siteOrigin(host: string | null | undefined, nodeEnv: string | undefined): string {
  const raw = (host ?? "").split(",")[0].trim().toLowerCase() || "localhost";
  const protocol = nodeEnv === "production" ? "https" : "http";
  return `${protocol}://${raw}`;
}
