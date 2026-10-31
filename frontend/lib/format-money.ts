/** Formats integer cents as `$900.00` instead of a bare decimal + currency code (#845). */
export function money(cents: number): string {
  return new Intl.NumberFormat("en-US", { style: "currency", currency: "USD" }).format(cents / 100);
}
