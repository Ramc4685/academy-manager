import { ImageResponse } from "next/og";
import { createElement } from "react";

import { OG_CARD_SIZE, OgCard, ogCardContent } from "@/lib/public-page/og-card";
import { loadPublicAcademyPage } from "@/lib/public-page/server-fetch";

/**
 * `GET /og-card`: the generated Open Graph card for this host's public page
 * (brief section 4, phase 1: name and place on night with the brand lane
 * line, so WhatsApp and Instagram previews look intentional with no photo).
 * Personal data never appears: only the academy name, age span and address.
 */
export async function GET(): Promise<Response> {
  const { result } = await loadPublicAcademyPage();
  if (result.kind === "unknown_host") {
    return new Response("Not found", { status: 404 });
  }
  return new ImageResponse(createElement(OgCard, { content: ogCardContent(result) }), {
    ...OG_CARD_SIZE,
    headers: { "Cache-Control": "public, max-age=300", Vary: "Host" },
  });
}
