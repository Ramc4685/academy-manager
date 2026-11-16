import type { Metadata } from "next";
import { notFound } from "next/navigation";

import { AcademyMark } from "@/components/ds/academy-mark";
import { PublicPageUnavailable } from "@/components/public-page/states";
import { safeHexColor, safeHttpsUrl } from "@/lib/public-page/format";
import {
  formatIssuedOn,
  loadSharedCertificate,
  type SharedCertificate,
} from "@/lib/public-page/shared-certificate";
import { contrastRatio, ensureContrast } from "@/lib/public-page/theme";

/**
 * `/c/[token]`: a certificate a parent chose to share (L5B). The academy comes
 * from the request host (the backend resolves it); a revoked, unshared or
 * unknown link is the same plain 404. Only a live share may be indexed: it is
 * there because the parent opted in. Every other state is noindex.
 */
type Params = { params: Promise<{ token: string }> };

function label(cert: SharedCertificate): string {
  return cert.level_number
    ? `Level ${cert.level_number} · ${cert.level_name}`
    : cert.level_name;
}

export async function generateMetadata({ params }: Params): Promise<Metadata> {
  const { token } = await params;
  const result = await loadSharedCertificate(token);
  if (result.kind !== "found")
    return { robots: { index: false, follow: false } };
  const cert = result.certificate;
  const title = `${cert.recipient_name} finished ${label(cert)} · ${cert.academy.name}`;
  return {
    title,
    description: `A certificate of achievement from ${cert.academy.name}.`,
    openGraph: { title, type: "website" },
    robots: { index: true, follow: false },
  };
}

export default async function SharedCertificatePage({ params }: Params) {
  const { token } = await params;
  const result = await loadSharedCertificate(token);
  if (result.kind === "not_found") notFound();
  if (result.kind === "unavailable") return <PublicPageUnavailable />;
  const cert = result.certificate;
  const accent = ensureContrast(
    safeHexColor(cert.academy.brand_color, "#1e3a8a"),
    "#ffffff",
  );
  const band = safeHexColor(cert.level_color, accent);
  const ink =
    contrastRatio(band, "#0f172a") >= contrastRatio(band, "#ffffff")
      ? "#0f172a"
      : "#ffffff";
  const logo = safeHttpsUrl(cert.academy.logo_url);
  return (
    <main className="min-h-screen bg-slate-50 px-4 py-10 text-slate-900">
      <article
        data-testid="shared-certificate"
        className="mx-auto flex max-w-xl flex-col overflow-hidden rounded-2xl bg-white shadow-[0_6px_20px_rgba(15,23,42,0.12)]"
        style={{ border: `3px solid ${accent}` }}
      >
        <div className="flex items-center gap-3 px-6 pt-6">
          {logo ? (
            <img
              src={logo}
              alt={cert.academy.name}
              style={{
                height: 44,
                width: "auto",
                maxWidth: 160,
                objectFit: "contain",
              }}
            />
          ) : (
            <AcademyMark name={cert.academy.name} size={44} />
          )}
          <p className="font-display text-lg font-bold leading-tight">
            {cert.academy.name}
          </p>
        </div>
        <div className="flex flex-col gap-2 px-6 py-8">
          <p
            className="font-display text-xl font-semibold"
            style={{ color: accent }}
          >
            Certificate of achievement
          </p>
          <p className="text-sm text-slate-600">This certifies that</p>
          <h1 className="font-display text-4xl font-bold tracking-[-0.02em]">
            {cert.recipient_name}
          </h1>
          <p className="text-sm text-slate-600">has mastered every skill in</p>
          <p className="font-display text-2xl font-bold">{label(cert)}</p>
        </div>
        <div
          className="flex flex-wrap items-end justify-between gap-3 px-6 py-4 text-sm"
          style={{ background: band, color: ink }}
        >
          <div>
            <p className="text-[11px] font-bold uppercase tracking-[0.14em] opacity-80">
              Awarded
            </p>
            <p className="font-semibold">{formatIssuedOn(cert.issued_on)}</p>
          </div>
          <div className="text-right">
            <p className="text-[11px] font-bold uppercase tracking-[0.14em] opacity-80">
              Certificate no.
            </p>
            <p className="break-all font-semibold">{cert.cert_number}</p>
          </div>
        </div>
      </article>
    </main>
  );
}
