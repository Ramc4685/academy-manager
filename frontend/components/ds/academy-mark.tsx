import { monogram, safeHttpsUrl } from "@/lib/public-page/format";

/**
 * Row 14: the shared academy mark for the admin, parent and coach shells (the
 * owner shell keeps the platform ShuttleMark — this is deliberately not used
 * there).
 *
 * `logo_url` renders as an `<img>` only when it is an absolute https URL
 * (`safeHttpsUrl`, shared with the public tenant page) — never a raw,
 * unvalidated URL, and never `http:`/`javascript:`/any other scheme. Every
 * other case — no logo, or a rejected URL — falls back to a monogram built
 * from the academy name (`monogram`, same helper the public page uses).
 */
interface AcademyMarkProps {
  name: string;
  logoUrl?: string | null;
  size?: number;
  /** Monogram background when there is no logo. */
  monogramBg?: string;
  /** Monogram text color when there is no logo. */
  monogramColor?: string;
  className?: string;
}

export function AcademyMark({
  name,
  logoUrl,
  size = 32,
  monogramBg = "#facc15",
  monogramColor = "#0a0f1c",
  className,
}: AcademyMarkProps) {
  const label = (name ?? "").trim() || "Academy";
  const src = safeHttpsUrl(logoUrl);

  if (src) {
    return (
      <img
        src={src}
        alt={label}
        width={size}
        height={size}
        className={className}
        style={{
          width: size,
          height: size,
          borderRadius: 6,
          objectFit: "cover",
          flexShrink: 0,
        }}
      />
    );
  }

  return (
    <span
      aria-hidden="true"
      className={className}
      style={{
        width: size,
        height: size,
        borderRadius: 6,
        flexShrink: 0,
        display: "inline-flex",
        alignItems: "center",
        justifyContent: "center",
        fontWeight: 700,
        fontSize: Math.max(10, Math.round(size * 0.42)),
        background: monogramBg,
        color: monogramColor,
      }}
    >
      {monogram(label)}
    </span>
  );
}
