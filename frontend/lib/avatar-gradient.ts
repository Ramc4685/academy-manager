/**
 * Per-child avatar gradients, derived from the name hash — genuinely dynamic,
 * so these stay as literal color stops (no single token pair covers a
 * rotating 5-way palette).
 *
 * Shared by the parent Children list and the kid-first Home cards so the same
 * child wears the same colour on both screens.
 */
/**
 * #843: every stop is a Rally / DS status hue. The purple→pink and
 * cobalt→indigo pairs that used to sit here were the only colours on these
 * cards with no token behind them.
 */
const GRADIENTS = [
  "linear-gradient(135deg,#2563eb,#1e3a8a)", // cobalt 600 → 900
  "linear-gradient(135deg,#059669,#0d9488)", // green → teal
  "linear-gradient(135deg,#d97706,#f59e0b)", // amber
  "linear-gradient(135deg,#475569,#0f172a)", // slate 600 → ink
  "linear-gradient(135deg,#0891b2,#2563eb)", // cyan → cobalt
];

export function nameGradient(s: string): string {
  let h = 0;
  for (let i = 0; i < s.length; i++) h = (h * 31 + s.charCodeAt(i)) & 0xffffffff;
  return GRADIENTS[Math.abs(h) % GRADIENTS.length];
}

/** First letter of a name, upper-cased; "S" when the name is empty. */
export function nameInitial(s: string): string {
  return s.trim()[0]?.toUpperCase() ?? "S";
}
