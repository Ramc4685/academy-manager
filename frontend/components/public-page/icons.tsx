import styles from "./public-page.module.css";

/** Decorative inline icons; every one is aria-hidden next to a text label. */

export function PinIcon() {
  return (
    <svg className={styles.icon} viewBox="0 0 24 24" aria-hidden="true">
      <path d="M12 21s-7-6.1-7-11.2A7 7 0 0 1 19 9.8C19 14.9 12 21 12 21z" />
      <circle cx="12" cy="9.8" r="2.4" />
    </svg>
  );
}

export function UserIcon() {
  return (
    <svg className={styles.icon} viewBox="0 0 24 24" aria-hidden="true">
      <circle cx="12" cy="8" r="3.6" />
      <path d="M4.5 20c1.2-3.6 4-5.4 7.5-5.4s6.3 1.8 7.5 5.4" />
    </svg>
  );
}

export function CheckIcon() {
  return (
    <svg className={styles.icon} viewBox="0 0 24 24" aria-hidden="true">
      <path d="M4.5 12.5l5 5L19.5 7" />
    </svg>
  );
}

export function ArrowIcon() {
  return (
    <svg className={styles.icon} viewBox="0 0 24 24" aria-hidden="true">
      <path d="M5 12h14M13 6l6 6-6 6" />
    </svg>
  );
}

export function PlusIcon() {
  return (
    <svg className={styles.icon} viewBox="0 0 24 24" aria-hidden="true">
      <path d="M12 5v14M5 12h14" />
    </svg>
  );
}

/**
 * Row 35: the CourtMastr footer credit's mark — the one-colour CourtMastr
 * logo (docs/design/logo, "Earned Stripes"), sport-neutral and drawn in
 * `currentColor` so it takes the footer's colour.
 */
export function CourtMastrMark() {
  return (
    <svg viewBox="60 40 136 170" aria-hidden="true">
      <g fill="none" stroke="currentColor" strokeWidth="24" strokeLinejoin="miter" strokeMiterlimit="10">
        <path d="M68 200L128 155L188 200" />
        <path d="M68 150L128 105L188 150" />
        <path d="M68 100L128 55L188 100" />
      </g>
    </svg>
  );
}

/** The drawn court: the no-photo hero state (brief section 8). */
export function CourtDrawing() {
  const lines = [
    "M4 4H406V187H4Z",
    "M4 18H406",
    "M4 173H406",
    "M27 4V187M383 4V187",
    "M146 4V187M264 4V187",
    "M4 95.5H146M264 95.5H406",
  ];
  return (
    <svg className={styles.court} viewBox="-30 -30 470 251" aria-hidden="true">
      <rect className={styles.courtFloor} x="-30" y="-30" width="470" height="251" rx="6" />
      {lines.map((d) => (
        <path key={d} className={styles.courtLine} pathLength={1} d={d} />
      ))}
    </svg>
  );
}
