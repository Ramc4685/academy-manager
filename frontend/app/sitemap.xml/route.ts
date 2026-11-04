import { sitemapUrls, sitemapXml } from "@/lib/public-page/crawl";
import { loadPublicAcademyPage } from "@/lib/public-page/server-fetch";

/**
 * `GET /sitemap.xml`, per host. Phase 1 lists only the root when the page is
 * indexable; single-class pages arrive in phase 2.
 */
export async function GET(): Promise<Response> {
  const { result, origin } = await loadPublicAcademyPage();
  if (result.kind === "unknown_host") {
    return new Response("Not found", { status: 404 });
  }
  return new Response(sitemapXml(sitemapUrls(result, origin)), {
    headers: {
      "Content-Type": "application/xml; charset=utf-8",
      "Cache-Control": "public, max-age=300",
      Vary: "Host",
    },
  });
}
