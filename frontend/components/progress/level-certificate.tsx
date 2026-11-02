"use client";

import { useEffect, useRef, useState } from "react";
import { AcademyMark } from "@/components/ds/academy-mark";
import type { CertificateDetail } from "@/lib/api/curriculum";
import {
  parseAcademyInstant,
  resolveAcademyTimeZone,
} from "@/lib/format/academy-time";
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
export function formatCertificateDate(
  value: string,
  academyTimezone?: string | null,
): string {
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

const caps = "text-[12px] font-bold uppercase tracking-[0.14em] text-slate-500";
/** Rally's volt, the shuttle-feather colour: fills and strokes only, never text on white. */
const VOLT = "#facc15";
const BAND_W = 296;

function CertificateLogo({ academy }: { academy: CertificateAcademy }) {
  const src = safeHttpsUrl(academy.logoUrl);
  if (!src) return <AcademyMark name={academy.name} size={52} />;
  // Logos are rarely square: keep the uploaded aspect ratio, never crop it.
  return (
    <img
      src={src}
      alt={academy.name}
      style={{ height: 56, width: "auto", maxWidth: 200, objectFit: "contain" }}
    />
  );
}

/** Long names step down so they stay on one line in the 600px column. */
function nameSize(name: string): number {
  if (name.length > 32) return 34;
  if (name.length > 24) return 40;
  if (name.length > 18) return 54;
  return 72;
}

/**
 * The shuttle's three feathers, shortest to longest, as on the academy mark:
 * one lights up per level reached, so level 2 shows two volt feathers.
 */
function LevelFeathers({ level }: { level: number | null }) {
  const lit = level ?? 3;
  return (
    <svg width="132" height="96" viewBox="0 0 132 96" aria-hidden="true">
      {["M14 86 L34 52", "M48 86 L78 32", "M82 86 L122 12"].map((d, i) => (
        <path
          key={d}
          d={d}
          stroke={i < lit ? VOLT : "rgba(255,255,255,0.22)"}
          strokeWidth="13"
          strokeLinecap="round"
        />
      ))}
    </svg>
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
  const columns = detail.skills.length > 8 ? 3 : 2;
  return (
    <div
      data-testid="level-certificate"
      className="box-border bg-white p-7 font-sans text-slate-900"
      style={{ width: PAGE_W, height: PAGE_H }}
    >
      <div
        className="box-border flex h-full overflow-hidden rounded-[10px]"
        style={{ border: `3px solid ${accent}` }}
      >
        <div className="flex min-w-0 flex-1 flex-col justify-between px-14 pb-11 pt-10">
          <div className="flex items-center gap-4">
            <CertificateLogo academy={academy} />
            <div className="flex flex-col gap-1">
              <p className="font-display text-[19px] font-bold leading-tight">
                {academy.name}
              </p>
              <p className={caps}>{cert.program_name}</p>
            </div>
          </div>

          <div className="flex flex-col gap-3">
            <p
              className="font-display text-[30px] font-semibold tracking-[-0.01em]"
              style={{ color: accent }}
            >
              Certificate of achievement
            </p>
            <p className="text-[16px] text-slate-600">This certifies that</p>
            <p
              className="self-start whitespace-nowrap font-display font-bold leading-none tracking-[-0.03em]"
              style={{
                fontSize: nameSize(cert.student_name),
                // A volt marker stroke behind the lower half of the name.
                background: `linear-gradient(transparent 58%, ${VOLT} 58%, ${VOLT} 92%, transparent 92%)`,
                padding: "0 6px",
                marginLeft: -6,
              }}
            >
              {cert.student_name}
            </p>
            <p className="mt-2 text-[16px] text-slate-600">
              has mastered every skill in
            </p>
            <p className="font-display text-[28px] font-bold leading-tight">
              {levelLabel(detail)}
            </p>
          </div>

          {detail.skills.length > 0 ? (
            <ul
              className="grid gap-x-6 gap-y-2.5 border-t border-slate-200 pt-5"
              style={{
                gridTemplateColumns: `repeat(${columns}, minmax(0, 1fr))`,
              }}
            >
              {detail.skills.map((skill) => (
                <li
                  key={skill}
                  className="flex items-center gap-2.5 text-[15px] font-medium"
                >
                  <svg
                    width="20"
                    height="20"
                    viewBox="0 0 20 20"
                    aria-hidden="true"
                    className="shrink-0"
                  >
                    <circle cx="10" cy="10" r="10" fill={VOLT} />
                    <path
                      d="M5.8 10.4l2.8 2.8 5.6-6.2"
                      fill="none"
                      stroke="#0f172a"
                      strokeWidth="2.2"
                      strokeLinecap="round"
                      strokeLinejoin="round"
                    />
                  </svg>
                  {skill}
                </li>
              ))}
            </ul>
          ) : (
            <div />
          )}

          <div className="grid grid-cols-2 gap-10">
            <div className="flex flex-col gap-1.5">
              <p className="font-display text-[17px] font-semibold">
                {formatCertificateDate(cert.completed_at, academy.timezone)}
              </p>
              <div className="border-t-2 border-slate-900" />
              <p className="text-[13px] text-slate-500">Date completed</p>
            </div>
            {/* No coach is recorded on the certificate (auto level-ups are
                issued by the system), so the academy signs it. */}
            <div className="flex flex-col gap-1.5">
              <p className="truncate font-display text-[17px] font-semibold">
                {academy.name}
              </p>
              <div className="border-t-2 border-slate-900" />
              <p className="text-[13px] text-slate-500">Awarded by</p>
            </div>
          </div>
        </div>

        <div
          className="flex shrink-0 flex-col items-center justify-between px-8 pb-10 pt-14 text-white"
          style={{ width: BAND_W, background: accent }}
        >
          <LevelFeathers level={detail.level_number} />
          {detail.level_number ? (
            <div className="flex flex-col items-center">
              <p className="text-[15px] font-bold uppercase tracking-[0.3em] text-white/80">
                Level
              </p>
              <p
                className="font-display text-[200px] font-extrabold leading-none tracking-[-0.04em]"
                style={{ color: VOLT }}
              >
                {detail.level_number}
              </p>
            </div>
          ) : (
            <p
              className="font-display text-[44px] font-extrabold"
              style={{ color: VOLT }}
            >
              Complete
            </p>
          )}
          <div className="flex flex-col items-center gap-1 text-center">
            <p className="text-[11px] font-bold uppercase tracking-[0.14em] text-white/70">
              Certificate no.
            </p>
            <p className="break-all text-[12px] font-semibold text-white/90">
              {cert.cert_number}
            </p>
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
