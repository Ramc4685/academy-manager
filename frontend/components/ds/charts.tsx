"use client";

interface SparklineProps {
  values: number[];
  w?: number;
  h?: number;
  color?: string;
  fill?: boolean;
}

export function Sparkline({
  values,
  w = 120,
  h = 32,
  color = "#2563eb",
  fill = true,
}: SparklineProps) {
  if (values.length < 2) return null;
  const min = Math.min(...values);
  const max = Math.max(...values);
  const range = max - min || 1;
  const pts = values.map((v, i) => {
    const x = (i / (values.length - 1)) * (w - 2) + 1;
    const y = h - 2 - ((v - min) / range) * (h - 4);
    return `${x.toFixed(1)},${y.toFixed(1)}`;
  });
  const d = `M${pts.join(" L")}`;
  const last = pts[pts.length - 1];
  const [lastX, lastY] = last.split(",");
  const fd = `M${pts[0].split(",")[0]},${h} L${pts.join(" L")} L${lastX},${h} Z`;
  return (
    <svg width={w} height={h} viewBox={`0 0 ${w} ${h}`} style={{ overflow: "visible" }}>
      {fill && <path d={fd} fill={color} opacity={0.08} />}
      <path d={d} fill="none" stroke={color} strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round" />
      <circle cx={lastX} cy={lastY} r="2.5" fill={color} />
    </svg>
  );
}

interface MiniBarsProps {
  values: number[];
  w?: number;
  h?: number;
  color?: string;
  highlight?: number;
}

export function MiniBars({
  values,
  w = 240,
  h = 80,
  color = "#2563eb",
  highlight,
}: MiniBarsProps) {
  const max = Math.max(...values) || 1;
  const bw = w / values.length - 4;
  return (
    <svg width={w} height={h} viewBox={`0 0 ${w} ${h}`}>
      {values.map((v, i) => {
        const bh = (v / max) * (h - 4);
        const c = highlight === i ? "#facc15" : color;
        return (
          <rect
            key={i}
            x={i * (bw + 4)}
            y={h - bh}
            width={bw}
            height={bh}
            rx="2"
            fill={c}
            opacity={highlight === i ? 1 : 0.85}
          />
        );
      })}
    </svg>
  );
}

interface RingProps {
  value?: number;
  size?: number;
  stroke?: number;
  color?: string;
  bg?: string;
  label?: string;
  sub?: string;
}

export function Ring({
  value = 0.6,
  size = 96,
  stroke = 10,
  color = "#2563eb",
  bg = "#e2e8f0",
  label,
  sub,
}: RingProps) {
  const r = (size - stroke) / 2;
  const c = 2 * Math.PI * r;
  return (
    <div className="relative shrink-0" style={{ width: size, height: size }}>
      <svg width={size} height={size}>
        <circle cx={size / 2} cy={size / 2} r={r} fill="none" stroke={bg} strokeWidth={stroke} />
        <circle
          cx={size / 2}
          cy={size / 2}
          r={r}
          fill="none"
          stroke={color}
          strokeWidth={stroke}
          strokeDasharray={c}
          strokeDashoffset={c * (1 - value)}
          strokeLinecap="round"
          transform={`rotate(-90 ${size / 2} ${size / 2})`}
        />
      </svg>
      {label && (
        <div className="absolute inset-0 flex flex-col items-center justify-center">
          <span
            className="font-display font-bold tracking-[-0.02em] leading-none text-rally-ink"
            style={{ fontSize: size * 0.26 }}
          >
            {label}
          </span>
          {sub && (
            <span className="mt-1 font-mono text-[9px] font-bold tracking-[0.15em] uppercase text-rally-muted">
              {sub}
            </span>
          )}
        </div>
      )}
    </div>
  );
}
