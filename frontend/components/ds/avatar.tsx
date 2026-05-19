"use client";

const AV_COLORS: ReadonlyArray<readonly [string, string]> = [
  ["#dbeafe", "#1d4ed8"],
  ["#fef9c3", "#854d0e"],
  ["#dcfce7", "#166534"],
  ["#fce7f3", "#9d174d"],
  ["#fed7aa", "#9a3412"],
  ["#e0e7ff", "#3730a3"],
  ["#cffafe", "#155e75"],
  ["#fee2e2", "#991b1b"],
];

function avHash(s: string): number {
  let h = 0;
  for (let i = 0; i < s.length; i++) {
    h = ((h * 31 + s.charCodeAt(i)) | 0);
  }
  return Math.abs(h) % AV_COLORS.length;
}

interface AvatarProps {
  name?: string;
  size?: number;
  square?: boolean;
}

export function Avatar({ name = "", size = 36, square = false }: AvatarProps) {
  const initials =
    name
      .split(" ")
      .filter(Boolean)
      .slice(0, 2)
      .map((s) => s[0])
      .join("")
      .toUpperCase() || "?";
  const [bg, fg] = AV_COLORS[avHash(name)];
  return (
    <span
      className="inline-flex items-center justify-center shrink-0 font-display font-bold tracking-[0.02em]"
      style={{
        width: size,
        height: size,
        borderRadius: square ? 6 : "50%",
        background: bg,
        color: fg,
        fontSize: size * 0.38,
      }}
    >
      {initials}
    </span>
  );
}
