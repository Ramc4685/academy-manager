/**
 * Per-host robots.txt and sitemap.xml bodies (brief section 4). Pure so the
 * route handlers stay thin and every branch is unit tested.
 *
 * robots never disallows the public page itself: an unpublished or empty page
 * carries a `noindex` meta, which a crawler can only see if it may fetch it.
 */

import { isIndexable } from "./page-model";
import type { PublicPageResult } from "./types";

const PRIVATE_PREFIXES = ["/admin", "/coach", "/parent", "/platform", "/api/", "/post-login"];

export function robotsTxt(result: PublicPageResult, origin: string): string {
  const lines = ["User-agent: *", "Allow: /"];
  for (const prefix of PRIVATE_PREFIXES) lines.push(`Disallow: ${prefix}`);
  if (result.kind !== "unknown_host") lines.push("", `Sitemap: ${origin}/sitemap.xml`);
  return `${lines.join("\n")}\n`;
}

function xmlEscape(value: string): string {
  return value
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;")
    .replace(/'/g, "&apos;");
}

/** The root URL when this host has an indexable page (or is the product host). */
export function sitemapUrls(result: PublicPageResult, origin: string): string[] {
  if (result.kind === "platform" || isIndexable(result)) return [`${origin}/`];
  return [];
}

export function sitemapXml(urls: string[]): string {
  const body = urls.map((url) => `  <url><loc>${xmlEscape(url)}</loc></url>`).join("\n");
  return [
    '<?xml version="1.0" encoding="UTF-8"?>',
    '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">',
    ...(body ? [body] : []),
    "</urlset>",
    "",
  ].join("\n");
}
