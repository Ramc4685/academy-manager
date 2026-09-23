import type { Metadata } from "next";
import { headers } from "next/headers";
import { notFound } from "next/navigation";
import { Suspense } from "react";

import { PlatformLandingPage } from "@/components/marketing/PlatformLandingPage";
import { PublicTenantPage } from "@/components/public-page/PublicTenantPage";
import {
  NotPublishedPage,
  PublicPageLoading,
  PublicPageUnavailable,
} from "@/components/public-page/states";
import { isPlatformProductHost } from "@/lib/public-page/host";
import { buildPublicPageMetadata } from "@/lib/public-page/metadata";
import { loadPublicAcademyPage } from "@/lib/public-page/server-fetch";
import { buildPublicPageJsonLd } from "@/lib/public-page/structured-data";

/**
 * `/` is host-aware (Lane B3, brief section 4):
 *
 * - a product host (academy.courtmastr.com, see lib/public-page/host.ts)
 *   keeps the CourtMastr landing page, without calling the backend;
 * - any other host is a tenant host and renders that academy's public page
 *   from `GET /api/v2/public/academy`: published, nothing published yet,
 *   trials closed (a flag inside the published shape), or the backend's
 *   404 for a host no academy serves, which becomes notFound().
 *
 * `frontend/middleware.ts` only matches the persona prefixes, so `/` is never
 * redirected by the persona gate and signed-in users keep their routing.
 */
export async function generateMetadata(): Promise<Metadata> {
  const { result, origin } = await loadPublicAcademyPage();
  if (result.kind === "unknown_host") notFound();
  return buildPublicPageMetadata(result, origin) ?? {};
}

async function PublicAcademyRoot() {
  const { result, origin } = await loadPublicAcademyPage();
  switch (result.kind) {
    case "platform":
      return <PlatformLandingPage />;
    case "unknown_host":
      notFound();
    case "not_published":
      return <NotPublishedPage page={result.page} />;
    case "published":
      return (
        <PublicTenantPage page={result.page} jsonLd={buildPublicPageJsonLd(result.page, origin)} />
      );
    case "unavailable":
    default:
      return <PublicPageUnavailable />;
  }
}

export default async function RootPage() {
  const host = (await headers()).get("host");
  if (isPlatformProductHost(host, process.env)) return <PlatformLandingPage />;
  return (
    <Suspense fallback={<PublicPageLoading />}>
      <PublicAcademyRoot />
    </Suspense>
  );
}
