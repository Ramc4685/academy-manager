/** "1,234": a count for display. Lives here so the S05 locale guard can stay strict. */
export function formatCount(value: number): string {
  return value.toLocaleString("en-US");
}
