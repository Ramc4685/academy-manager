"use client";

import type { ReactElement } from "react";

type IconFactory = (size?: number, color?: string) => ReactElement;

const stroke = (path: ReactElement, size: number, color: string, sw = "2"): ReactElement => (
  <svg
    width={size}
    height={size}
    viewBox="0 0 24 24"
    fill="none"
    stroke={color}
    strokeWidth={sw}
    strokeLinecap="round"
    strokeLinejoin="round"
    aria-hidden="true"
  >
    {path}
  </svg>
);

export const Icon: Record<string, IconFactory> = {
  arrow: (s = 16, c = "currentColor") => stroke(<path d="M5 12h14M13 5l7 7-7 7" />, s, c),
  arrowL: (s = 16, c = "currentColor") => stroke(<path d="M19 12H5M11 5l-7 7 7 7" />, s, c),
  chevR: (s = 16, c = "currentColor") => stroke(<path d="M9 6l6 6-6 6" />, s, c, "2.2"),
  chevD: (s = 16, c = "currentColor") => stroke(<path d="M6 9l6 6 6-6" />, s, c, "2.2"),
  plus: (s = 16, c = "currentColor") => stroke(<path d="M12 5v14M5 12h14" />, s, c),
  check: (s = 16, c = "currentColor") => stroke(<path d="M20 6L9 17l-5-5" />, s, c, "2.4"),
  x: (s = 16, c = "currentColor") => stroke(<path d="M18 6L6 18M6 6l12 12" />, s, c, "2.2"),
  search: (s = 16, c = "currentColor") =>
    stroke(
      <>
        <circle cx="11" cy="11" r="7" />
        <path d="M21 21l-4.3-4.3" />
      </>,
      s,
      c,
    ),
  bell: (s = 16, c = "currentColor") =>
    stroke(
      <>
        <path d="M6 8a6 6 0 0112 0c0 7 3 9 3 9H3s3-2 3-9" />
        <path d="M10 21a2 2 0 004 0" />
      </>,
      s,
      c,
    ),
  user: (s = 16, c = "currentColor") =>
    stroke(
      <>
        <circle cx="12" cy="8" r="4" />
        <path d="M4 21c0-4 4-7 8-7s8 3 8 7" />
      </>,
      s,
      c,
    ),
  filter: (s = 16, c = "currentColor") =>
    stroke(<path d="M3 5h18M6 12h12M10 19h4" />, s, c),
  dl: (s = 16, c = "currentColor") =>
    stroke(<path d="M12 3v12M7 10l5 5 5-5M5 21h14" />, s, c),
  more: (s = 16, c = "currentColor") => (
    <svg width={s} height={s} viewBox="0 0 24 24" fill={c} aria-hidden="true">
      <circle cx="5" cy="12" r="1.6" />
      <circle cx="12" cy="12" r="1.6" />
      <circle cx="19" cy="12" r="1.6" />
    </svg>
  ),
  calendar: (s = 16, c = "currentColor") =>
    stroke(
      <>
        <rect x="3" y="5" width="18" height="16" rx="2" />
        <path d="M3 10h18M8 3v4M16 3v4" />
      </>,
      s,
      c,
    ),
  clock: (s = 16, c = "currentColor") =>
    stroke(
      <>
        <circle cx="12" cy="12" r="9" />
        <path d="M12 7v5l3 2" />
      </>,
      s,
      c,
    ),
  card: (s = 16, c = "currentColor") =>
    stroke(
      <>
        <rect x="2" y="6" width="20" height="13" rx="2" />
        <path d="M2 11h20M6 16h4" />
      </>,
      s,
      c,
    ),
  msg: (s = 16, c = "currentColor") =>
    stroke(<path d="M21 12a8 8 0 01-12 7l-5 1 1-5a8 8 0 1116-3z" />, s, c),
  spark: (s = 16, c = "currentColor") =>
    stroke(<path d="M12 3l2 6 6 2-6 2-2 6-2-6-6-2 6-2z" />, s, c),
  pin: (s = 16, c = "currentColor") =>
    stroke(<path d="M12 21V12M8 12h8l-1-5a3 3 0 00-6 0z" />, s, c),
  home: (s = 16, c = "currentColor") =>
    stroke(
      <path d="M3 11l9-7 9 7v9a2 2 0 01-2 2h-4v-7H9v7H5a2 2 0 01-2-2z" />,
      s,
      c,
    ),
  pay: (s = 16, c = "currentColor") =>
    stroke(
      <path d="M12 1v22M5 8h11.5a3.5 3.5 0 010 7h-9a3.5 3.5 0 000 7H19" />,
      s,
      c,
    ),
  attend: (s = 16, c = "currentColor") =>
    stroke(
      <>
        <path d="M9 11l3 3 8-8" />
        <path d="M21 12v7a2 2 0 01-2 2H5a2 2 0 01-2-2V5a2 2 0 012-2h11" />
      </>,
      s,
      c,
    ),
  chart: (s = 16, c = "currentColor") =>
    stroke(<path d="M3 3v18h18M7 14l4-4 4 4 5-6" />, s, c),
  whistle: (s = 16, c = "currentColor") =>
    stroke(
      <>
        <circle cx="9" cy="13" r="6" />
        <path d="M9 7V5a2 2 0 012-2h2M15 13l5-3" />
      </>,
      s,
      c,
    ),
  list: (s = 16, c = "currentColor") =>
    stroke(
      <path d="M8 6h13M8 12h13M8 18h13M3 6h.01M3 12h.01M3 18h.01" />,
      s,
      c,
    ),
  cog: (s = 16, c = "currentColor") =>
    stroke(
      <>
        <circle cx="12" cy="12" r="3" />
        <path d="M19.4 15a1.7 1.7 0 00.3 1.8l.1.1a2 2 0 11-2.8 2.8l-.1-.1a1.7 1.7 0 00-1.8-.3 1.7 1.7 0 00-1 1.5V21a2 2 0 11-4 0v-.1a1.7 1.7 0 00-1-1.5 1.7 1.7 0 00-1.8.3l-.1.1a2 2 0 11-2.8-2.8l.1-.1a1.7 1.7 0 00.3-1.8 1.7 1.7 0 00-1.5-1H3a2 2 0 110-4h.1a1.7 1.7 0 001.5-1 1.7 1.7 0 00-.3-1.8l-.1-.1a2 2 0 112.8-2.8l.1.1a1.7 1.7 0 001.8.3h0a1.7 1.7 0 001-1.5V3a2 2 0 114 0v.1a1.7 1.7 0 001 1.5 1.7 1.7 0 001.8-.3l.1-.1a2 2 0 112.8 2.8l-.1.1a1.7 1.7 0 00-.3 1.8v0a1.7 1.7 0 001.5 1H21a2 2 0 110 4h-.1a1.7 1.7 0 00-1.5 1z" />
      </>,
      s,
      c,
    ),
  trophy: (s = 16, c = "currentColor") =>
    stroke(
      <>
        <path d="M6 4h12v4a6 6 0 01-12 0z" />
        <path d="M18 6h3v2a3 3 0 01-3 3M6 6H3v2a3 3 0 003 3M12 14v4M8 22h8" />
      </>,
      s,
      c,
    ),
  signal: (s = 16, c = "currentColor") =>
    stroke(<path d="M4 18v-2M9 18v-6M14 18v-10M19 18V4" />, s, c),
};
