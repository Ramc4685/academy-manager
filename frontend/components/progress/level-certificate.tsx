"use client";

import { useEffect, useRef, useState } from "react";
import { AcademyMark } from "@/components/ds/academy-mark";
import type { CertificateDetail } from "@/lib/api/curriculum";
import { parseAcademyInstant, resolveAcademyTimeZone } from "@/lib/format/academy-time";
import { safeHexColor, safeHttpsUrl } from "@/lib/public-page/format";
import { ensureContrast } from "@/lib/public-page/theme";

/** Letter landscape at 96 CSS px per inch: 11in x 8.5in. */
const PAGE_W = 1056;
const PAGE_H = 816;
const DEFAULT_ACCENT = "#1e3a8a";

export interface CertificateAcademy {
  name: string;
  logoUrl?: string | null;
  brandColor?: string | null;
  timezone?: string | null;
}

/** The academy brand colour, darkened until it reads on white paper. */
export function certificateAccent(brandColor?: string | null): string {
  return ensureContrast(safeHexColor(brandColor, DEFAULT_ACCENT), "#ffffff");
}

/** "October 30, 2026" in the academy's zone (naive timestamps are UTC). */
export function formatCertificateDate(value: string, academyTimezone?: string | null): string {
  return parseAcademyInstant(value).toLocaleDateString("en-US", {
    month: "long",
    day: "numeric",
    year: "numeric",
    timeZone: resolveAcademyTimeZone(academyTimezone).timeZone,
  });
}

export function levelLabel(detail: CertificateDetail): string {
  const name = detail.certificate.level_name;
  return detail.level_number ? `Level ${detail.level_number} · ${name}` : name;
}

const caps = "text-[12px] font-bold uppercase tracking-[0.12em] text-slate-600";

function CertificateLogo({ academy }: { academy: CertificateAcademy }) {
  const src = safeHttpsUrl(academy.logoUrl);
  if (!src) return <AcademyMark name={academy.name} size={56} />;
  // Logos are rarely square: keep the uploaded aspect ratio, never crop it.
  return (
    <img
      src={src}
      alt={academy.name}
      style={{ height: 64, width: "auto", maxWidth: 180, objectFit: "contain" }}
    />
  );
}

/** The printable certificate, laid out at its real Letter-landscape size. */
export function LevelCertificate({
  detail,
  academy,
}: {
  detail: CertificateDetail;
  academy: CertificateAcademy;
}) {
  const cert = detail.certificate;
  const accent = certificateAccent(academy.brandColor);
  return (
    <div
      data-testid="level-certificate"
      className="box-border bg-white p-7 font-sans text-slate-900"
      style={{ width: PAGE_W, height: PAGE_H }}
    >
      <div className="box-border h-full p-1.5" style={{ border: `3px solid ${accent}` }}>
        <div
          className="box-border flex h-full flex-col items-center justify-between px-16 pb-8 pt-9"
          style={{ border: `1px solid ${accent}` }}
        >
          <div className="flex w-full items-start justify-between">
            <div className="flex items-center gap-3.5">
              <CertificateLogo academy={academy} />
              <div className="flex flex-col gap-0.5">
                <p className="font-display text-[20px] font-bold">{academy.name}</p>
                <p className={caps}>{cert.program_name}</p>
              </div>
            </div>
            <div className="flex flex-col items-end gap-0.5">
              <p className={caps}>Certificate no.</p>
              <p className="text-[13px] font-semibold text-slate-700">{cert.cert_number}</p>
            </div>
          </div>

          <div className="flex flex-col items-center gap-2.5 text-center">
            <p
              className="text-[14px] font-bold uppercase tracking-[0.24em]"
              style={{ color: accent }}
            >
              Certificate of achievement
            </p>
            <p className="text-[17px] text-slate-600">This certifies that</p>
            <p className="border-b-2 border-slate-300 px-10 pb-2.5 font-display text-[64px] font-bold leading-[1.05]">
              {cert.student_name}
            </p>
            <p className="mt-1.5 text-[17px] text-slate-600">has mastered every skill in</p>
            <p className="font-display text-[36px] font-bold" style={{ color: accent }}>
              {levelLabel(detail)}
            </p>
          </div>

          {detail.skills.length > 0 ? (
            <div className="flex flex-col items-center gap-2.5">
              <p className={caps}>Skills mastered</p>
              <ul className="flex max-w-[800px] flex-wrap justify-center gap-2">
                {detail.skills.map((skill) => (
                  <li
                    key={skill}
                    className="flex items-center gap-1.5 rounded-full border border-slate-300 px-3 py-1.5 text-[14px] font-semibold text-slate-800"
                  >
                    <svg width="14" height="14" viewBox="0 0 14 14" aria-hidden="true">
                      <path
                        d="M2.5 7.5l3 3 6-7"
                        fill="none"
                        stroke="#047857"
                        strokeWidth="2"
                        strokeLinecap="round"
                        strokeLinejoin="round"
                      />
                    </svg>
                    {skill}
                  </li>
                ))}
              </ul>
            </div>
          ) : (
            <div />
          )}

          <div className="grid w-full grid-cols-[1fr_auto_1fr] items-end gap-8">
            <div className="flex flex-col gap-1.5">
              <p className="font-display text-[18px] font-semibold">
                {formatCertificateDate(cert.completed_at, academy.timezone)}
              </p>
              <div className="w-[220px] border-t-[1.5px] border-slate-700" />
              <p className="text-[13px] text-slate-600">Date completed</p>
            </div>
            <svg width="112" height="112" viewBox="0 0 112 112" aria-hidden="true">
              <circle cx="56" cy="56" r="52" fill="#fef9c3" stroke={accent} strokeWidth="3" />
              <circle
                cx="56"
                cy="56"
                r="43"
                fill="none"
                stroke={accent}
                strokeWidth="1"
                strokeDasharray="3 4"
              />
              {detail.level_number ? (
                <>
                  <text
                    x="56"
                    y="44"
                    textAnchor="middle"
                    fontSize="12"
                    fontWeight="700"
                    letterSpacing="2"
                    fill={accent}
                  >
                    LEVEL
                  </text>
                  <text
                    x="56"
                    y="80"
                    textAnchor="middle"
                    fontSize="38"
                    fontWeight="700"
                    fill={accent}
                  >
                    {detail.level_number}
                  </text>
                </>
              ) : (
                <text
                  x="56"
                  y="61"
                  textAnchor="middle"
                  fontSize="13"
                  fontWeight="700"
                  fill={accent}
                >
                  COMPLETE
                </text>
              )}
            </svg>
            {/* No coach is recorded on the certificate (auto level-ups are
                issued by the system), so the academy signs it. */}
            <div className="flex flex-col items-end gap-1.5">
              <p className="font-display text-[18px] font-semibold">{academy.name}</p>
              <div className="w-[220px] border-t-[1.5px] border-slate-700" />
              <p className="text-[13px] text-slate-600">Awarded by</p>
            </div>
          </div>
        </div>
      </div>
    </div>
  );
}

/**
 * Shows the full-size certificate scaled to its container. The same DOM is
 * what prints: the print stylesheet hides the rest of the page and drops the
 * scale, so the paper copy is the certificate at 11in x 8.5in.
 */
export function CertificatePreview({
  detail,
  academy,
}: {
  detail: CertificateDetail;
  academy: CertificateAcademy;
}) {
  const frame = useRef<HTMLDivElement>(null);
  const [scale, setScale] = useState(0.34);
  useEffect(() => {
    const node = frame.current;
    if (!node) return;
    const fit = () => setScale(node.clientWidth / PAGE_W);
    fit();
    const observer = new ResizeObserver(fit);
    observer.observe(node);
    return () => observer.disconnect();
  }, []);
  return (
    <div className="rounded-md bg-white p-1.5 shadow-[0_6px_20px_rgba(15,23,42,0.12)]">
      <style>{PRINT_CSS}</style>
      <div
        ref={frame}
        className="relative w-full overflow-hidden"
        style={{ aspectRatio: `${PAGE_W} / ${PAGE_H}` }}
      >
        <div
          className="certificate-print absolute left-0 top-0 origin-top-left"
          style={{ transform: `scale(${scale})` }}
        >
          <LevelCertificate detail={detail} academy={academy} />
        </div>
      </div>
    </div>
  );
}

const PRINT_CSS = `
@media print {
  @page { size: letter landscape; margin: 0; }
  /* Hidden content still takes space: clip to one sheet so no blank pages follow. */
  html, body { background: #fff !important; height: 8.5in !important; overflow: hidden !important; }
  body * { visibility: hidden !important; }
  .certificate-print, .certificate-print * { visibility: visible !important; }
  .certificate-print {
    position: fixed !important;
    left: 0 !important;
    top: 0 !important;
    transform: none !important;
    -webkit-print-color-adjust: exact;
    print-color-adjust: exact;
  }
}
`;
