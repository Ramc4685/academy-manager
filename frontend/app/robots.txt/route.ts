import { robotsTxt } from "@/lib/public-page/crawl";
import { loadPublicAcademyPage } from "@/lib/public-page/server-fetch";

/** `GET /robots.txt`, per host: product host and tenant hosts alike. */
export async function GET(): Promise<Response> {
  const { result, origin } = await loadPublicAcademyPage();
  return new Response(robotsTxt(result, origin), {
    headers: {
      "Content-Type": "text/plain; charset=utf-8",
      "Cache-Control": "public, max-age=300",
      Vary: "Host",
    },
  });
}
