import type { Route } from "next";
import Link from "next/link";
import {
  CertificatePreview,
  formatCertificateDate,
  levelLabel,
  type CertificateAcademy,
} from "@/components/progress/level-certificate";
import type { CertificateDetail } from "@/lib/api/curriculum";

/**
 * Share a short note and this page's link from the phone's share sheet.
 * Without a share sheet (most desktops), fall back to print so the family
 * can still save the PDF. Nothing is posted anywhere.
 */
export async function shareCertificate(
  detail: CertificateDetail,
  academyName: string,
  nav: Pick<Navigator, "share"> | undefined = typeof navigator === "undefined"
    ? undefined
    : navigator,
  print: () => void = () => window.print(),
): Promise<void> {
  const cert = detail.certificate;
  if (!nav?.share) {
    print();
    return;
  }
  try {
    await nav.share({
      title: `${cert.student_name}: ${levelLabel(detail)}`,
      text: `${cert.student_name} finished ${levelLabel(detail)} at ${academyName}!`,
      url: window.location.href,
    });
  } catch {
    // The parent closed the share sheet: nothing to do.
  }
}

export function CertificateScreen({
  detail,
  academy,
  progressHref,
  onPrint,
  onShare,
}: {
  detail: CertificateDetail;
  academy: CertificateAcademy;
  progressHref: Route;
  onPrint: () => void;
  onShare: () => void;
}) {
  const cert = detail.certificate;
  const firstName = cert.student_name.split(" ")[0] || cert.student_name;
  const completed = formatCertificateDate(cert.completed_at, academy.timezone);
  const count = detail.skills.length;
  return (
    <div className="mx-auto max-w-xl space-y-5" data-testid="parent-certificate">
      <div className="flex items-center gap-2">
        <Link
          href={progressHref}
          aria-label={`Back to ${firstName}'s progress`}
          className="-ml-3 flex h-11 w-11 items-center justify-center text-rally-ink"
        >
          <svg width="20" height="20" viewBox="0 0 20 20" aria-hidden="true">
            <path
              d="M12.5 4l-6 6 6 6"
              fill="none"
              stroke="currentColor"
              strokeWidth="2"
              strokeLinecap="round"
              strokeLinejoin="round"
            />
          </svg>
        </Link>
        <h1 className="font-display text-[17px] font-bold text-rally-ink">
          {detail.level_number ? `Level ${detail.level_number} certificate` : "Certificate"}
        </h1>
      </div>

      <div className="space-y-1">
        <p className="text-xs font-bold uppercase tracking-[0.08em] text-rally-volt-700">
          Level complete
        </p>
        <p className="font-display text-2xl font-bold leading-tight text-rally-ink">
          {firstName} finished {cert.level_name}
        </p>
        <p className="text-sm text-rally-muted">
          {count > 0
            ? `All ${count} ${count === 1 ? "skill" : "skills"} mastered on ${completed}.`
            : `Completed on ${completed}.`}
        </p>
      </div>

      <CertificatePreview detail={detail} academy={academy} />

      <div className="flex flex-col gap-2.5">
        <button
          type="button"
          onClick={onPrint}
          className="flex min-h-12 items-center justify-center gap-2 rounded-xl bg-rally-volt-400 text-[15px] font-bold text-rally-ink"
        >
          <svg width="18" height="18" viewBox="0 0 18 18" aria-hidden="true">
            <path
              d="M5 7V2h8v5M5 13H3V7h12v6h-2M5 11h8v5H5z"
              fill="none"
              stroke="currentColor"
              strokeWidth="1.6"
              strokeLinejoin="round"
            />
          </svg>
          Print or save as PDF
        </button>
        <button
          type="button"
          onClick={onShare}
          className="flex min-h-12 items-center justify-center gap-2 rounded-xl border-[1.5px] border-rally-ink bg-white text-[15px] font-bold text-rally-ink"
        >
          <svg width="18" height="18" viewBox="0 0 18 18" aria-hidden="true">
            <path
              d="M9 2v10M5 6l4-4 4 4M3 10v6h12v-6"
              fill="none"
              stroke="currentColor"
              strokeWidth="1.6"
              strokeLinecap="round"
              strokeLinejoin="round"
            />
          </svg>
          Share with family
        </button>
        <p className="text-center text-xs text-rally-muted">
          Sharing uses your phone&apos;s share sheet. To send the certificate itself, save it as a
          PDF first. Nothing is posted publicly.
        </p>
      </div>

      {detail.next_level && (
        <Link
          href={progressHref}
          className="flex min-h-11 items-center gap-3 rounded-[14px] border border-rally-line bg-white p-3.5 text-rally-ink"
        >
          <span
            aria-hidden="true"
            className="flex h-9 w-9 items-center justify-center rounded-full bg-rally-volt-400 font-display font-bold"
          >
            {detail.next_level.number}
          </span>
          <span className="flex flex-1 flex-col gap-0.5">
            <span className="text-xs font-bold text-rally-muted">Up next</span>
            <span className="text-sm font-bold">
              Level {detail.next_level.number} · {detail.next_level.name}
            </span>
          </span>
          <svg width="16" height="16" viewBox="0 0 16 16" aria-hidden="true">
            <path
              d="M6 3l5 5-5 5"
              fill="none"
              stroke="currentColor"
              strokeWidth="1.8"
              strokeLinecap="round"
              strokeLinejoin="round"
            />
          </svg>
        </Link>
      )}
    </div>
  );
}
