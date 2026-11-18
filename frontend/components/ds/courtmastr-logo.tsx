/**
 * The CourtMastr platform logo ("Earned Stripes", docs/design/logo/README.md):
 * three chevrons, the newest (top) one volt, on a rounded Floodlit Night tile.
 * Geometry matches `docs/design/logo/build_logo.py` — change it there first.
 *
 * Platform brand only. Academy marks stay `AcademyMark` (per-academy logo_url).
 */
export function CourtMastrLogo({ size = 32, className }: { size?: number; className?: string }) {
  return (
    <svg
      width={size}
      height={size}
      viewBox="0 0 256 256"
      role="img"
      aria-label="CourtMastr"
      className={className}
      style={{ flexShrink: 0 }}
    >
      <rect width="256" height="256" rx="56" fill="#0a0f1c" />
      <g fill="none" strokeWidth="24" strokeLinejoin="miter" strokeMiterlimit="10">
        <path d="M68 200L128 155L188 200" stroke="#f8fafc" />
        <path d="M68 150L128 105L188 150" stroke="#f8fafc" />
        <path d="M68 100L128 55L188 100" stroke="#facc15" />
      </g>
    </svg>
  );
}
