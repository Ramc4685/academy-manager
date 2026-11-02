"use client";

import { useEffect, useLayoutEffect, useRef, useState } from "react";
import { AcademyMark } from "@/components/ds/academy-mark";
import type { CertificateDetail } from "@/lib/api/curriculum";
import {
  parseAcademyInstant,
  resolveAcademyTimeZone,
} from "@/lib/format/academy-time";
import { safeHexColor, safeHttpsUrl } from "@/lib/public-page/format";
import { contrastRatio, ensureContrast } from "@/lib/public-page/theme";

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

/**
 * The student's name on a volt marker stroke, shrunk from 72px until it fits
 * the column: glyph widths vary too much for a character count to predict.
 */
function FittedName({ name }: { name: string }) {
  const ref = useRef<HTMLParagraphElement>(null);
  const [size, setSize] = useState(72);
  useLayoutEffect(() => {
    const el = ref.current;
    const column = el?.parentElement;
    if (!el || !column) return;
    const fit = () => {
      el.style.fontSize = "72px";
      const avail = column.clientWidth;
      const width = el.scrollWidth;
      const next =
        width > avail && width > 0
          ? Math.max(28, Math.floor((72 * avail) / width))
          : 72;
      el.style.fontSize = `${next}px`;
      setSize(next);
    };
    fit();
    // The display face may still be loading on first paint.
    void document.fonts?.ready.then(fit);
  }, [name]);
  return (
    <p
      ref={ref}
      className="self-start whitespace-nowrap font-display font-bold leading-none tracking-[-0.03em]"
      style={{
        fontSize: size,
        // A volt marker stroke behind the lower half of the name.
        background: `linear-gradient(transparent 58%, ${VOLT} 58%, ${VOLT} 92%, transparent 92%)`,
        padding: "0 6px",
        marginLeft: -6,
      }}
    >
      {name}
    </p>
  );
}

/** Black-ish or white, whichever reads better on ``fill``. */
function inkOn(fill: string): string {
  return contrastRatio(fill, "#0f172a") >= contrastRatio(fill, "#ffffff")
    ? "#0f172a"
    : "#ffffff";
}

/**
 * The program's level ladder as shuttle feathers, shortest to longest, one per
 * level in that level's colour, earned up to ``reached``.
 */
function LevelFeathers({
  colors,
  reached,
  band,
  ink,
}: {
  colors: string[];
  reached: number;
  band: string;
  ink: string;
}) {
  const n = colors.length;
  const W = 232;
  const H = 104;
  const step = W / (n + 1.4);
  const sw = Math.min(14, step * 0.5);
  return (
    <svg width={W} height={H} viewBox={`0 0 ${W} ${H}`} aria-hidden="true">
      {colors.map((color, i) => {
        const len = (H - sw) * (0.4 + (0.6 * (i + 1)) / n);
        const x = sw / 2 + 2 + i * step;
        const y = H - sw / 2 - 2;
        const d = `M${x} ${y} L${x + len * 0.5} ${y - len * 0.866}`;
        // Earned: the level colour, edged in ink (strongly for this level, so
        // it shows on a band of its own colour). Not yet: a hollow outline.
        const earned = i < reached;
        return (
          <g key={i}>
            <path
              d={d}
              stroke={ink}
              strokeOpacity={i === reached - 1 ? 0.9 : earned ? 0.3 : 0.35}
              strokeWidth={sw + 4}
              strokeLinecap="round"
            />
            <path
              d={d}
              stroke={earned ? color : band}
              strokeWidth={sw}
              strokeLinecap="round"
            />
          </g>
        );
      })}
    </svg>
  );
}

/**
 * The skill bullet: the shuttle "o" from the BLNo mark (logo kit
 * blno-symbol-small.svg), its feathers in this level's colour.
 * Multi-academy: this is BLNo's symbol drawn for every academy. Before a
 * second academy goes live, swap it for a generic shuttle or the academy's
 * own uploaded symbol.
 */
function ShuttleMark({ feathers }: { feathers: string }) {
  // A white or pale level colour vanishes on paper: edge it in ink.
  const edge = contrastRatio(feathers, "#ffffff") < 1.6;
  return (
    <svg
      width="30"
      height="25"
      viewBox="33 45 212 174"
      aria-hidden="true"
      className="shrink-0"
    >
      <path
        fillRule="evenodd"
        fill="#0f172a"
        d="M37,156 a59,59 0 1 0 118,0 a59,59 0 1 0 -118,0 Z M71,156 a25,25 0 1 0 50,0 a25,25 0 1 0 -50,0 Z"
      />
      <g fill={feathers} stroke={edge ? "#0f172a" : "none"} strokeWidth="8">
        <path d="M137.79,101.61 L166.86,65.27 A16,16 0 0 0 139.14,49.27 L122.21,92.61 Z" />
        <path d="M150.45,114.28 L203.48,71.15 A16,16 0 0 0 180.85,48.52 L137.72,101.55 Z" />
        <path d="M159.39,129.79 L240.83,90.86 A16,16 0 0 0 224.83,63.14 L150.39,114.21 Z" />
      </g>
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
  const ladder = detail.levels.map((lvl) => safeHexColor(lvl.color, accent));
  const levelIndex = detail.level_number ? detail.level_number - 1 : -1;
  // The band wears this level's curriculum colour (the academy colour if the
  // level is gone); the number is volt wherever volt still reads on it.
  const band = ladder[levelIndex] ?? accent;
  const ink = inkOn(band);
  const numberColor = contrastRatio(VOLT, band) >= 3 ? VOLT : ink;
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
            <FittedName name={cert.student_name} />
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
                  <ShuttleMark feathers={band} />
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
          className="flex shrink-0 flex-col items-center justify-between px-8 pb-10 pt-14"
          style={{ width: BAND_W, background: band, color: ink }}
        >
          {ladder.length > 0 ? (
            <LevelFeathers
              colors={ladder}
              reached={levelIndex + 1}
              band={band}
              ink={ink}
            />
          ) : (
            <div />
          )}
          {detail.level_number ? (
            <div className="flex flex-col items-center">
              <p className="text-[15px] font-bold uppercase tracking-[0.3em] opacity-80">
                Level
              </p>
              <p
                className="font-display text-[200px] font-extrabold leading-none tracking-[-0.04em]"
                style={{ color: numberColor }}
              >
                {detail.level_number}
              </p>
              {ladder.length > 0 ? (
                <p className="text-[14px] font-semibold opacity-80">
                  of {ladder.length}
                </p>
              ) : null}
            </div>
          ) : (
            <p
              className="font-display text-[44px] font-extrabold"
              style={{ color: numberColor }}
            >
              Complete
            </p>
          )}
          <div className="flex flex-col items-center gap-1 text-center">
            <p className="text-[11px] font-bold uppercase tracking-[0.14em] opacity-70">
              Certificate no.
            </p>
            <p className="break-all text-[12px] font-semibold opacity-90">
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
