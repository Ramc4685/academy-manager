import { AcademyMark } from "@/components/ds/academy-mark";
import { brand } from "@/lib/brand";

/**
 * Row 15: the login/register hero and mobile header. On an academy host it
 * shows that academy's name and mark (falling back to a monogram, same rule
 * as the shells); on the platform host it keeps CourtMastr/`brand.companyName`
 * unchanged.
 */
export function BrandLockup({
  tone,
  academyName,
  logoUrl,
  brandColor,
}: {
  tone: "dark" | "light";
  /** Null on the platform host: render CourtMastr, not an academy. */
  academyName: string | null;
  logoUrl?: string | null;
  brandColor?: string | null;
}) {
  const text = tone === "dark" ? "text-white" : "text-slate-900";
  const subtext = tone === "dark" ? "text-white/70" : "text-slate-500";
  const isAcademyHost = academyName != null && academyName.trim().length > 0;
  const title = isAcademyHost ? academyName : brand.productName;
  const subtitle = isAcademyHost ? brand.productName : brand.companyName;

  return (
    <div className="flex items-center gap-3">
      <AcademyMark
        name={title}
        logoUrl={isAcademyHost ? logoUrl : null}
        size={40}
        monogramBg={(isAcademyHost && brandColor) || "#facc15"}
        monogramColor="#0f172a"
        className="rounded-lg"
      />
      <div>
        <div className={`font-display text-lg font-bold leading-6 ${text}`}>{title}</div>
        <div className={`text-[11px] uppercase ${subtext}`}>{subtitle}</div>
      </div>
    </div>
  );
}
