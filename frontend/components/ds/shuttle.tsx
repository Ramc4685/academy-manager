"use client";

interface ShuttleMarkProps {
  size?: number;
  color?: string;
}

export function ShuttleMark({ size = 14, color = "#facc15" }: ShuttleMarkProps) {
  return (
    <svg width={size} height={size} viewBox="0 0 24 24" fill="none" aria-hidden="true">
      <path
        d="M12 2 L8 8 L4 6 L8 12 L4 18 L8 16 L12 22 L16 16 L20 18 L16 12 L20 6 L16 8 Z"
        fill={color}
        stroke={color}
        strokeWidth="0.5"
        strokeLinejoin="round"
      />
      <circle cx="12" cy="12" r="2.5" fill="#fff" stroke={color} strokeWidth="1" />
    </svg>
  );
}
