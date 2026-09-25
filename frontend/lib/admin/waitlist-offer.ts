/**
 * X2: an `offered` waitlist row is holding a seat for a family that has not
 * answered yet. Admin views show when that hold ends (the hourly sweep then
 * offers the seat to the next family).
 */
export function offerExpiryLabel(iso: string | null | undefined): string | null {
  if (!iso) return null;
  const when = new Date(iso);
  if (Number.isNaN(when.getTime())) return null;
  const day = when.toLocaleDateString([], { weekday: "short", month: "short", day: "numeric" });
  const time = when.toLocaleTimeString([], { hour: "numeric", minute: "2-digit" });
  return `Held until ${day}, ${time}`;
}
