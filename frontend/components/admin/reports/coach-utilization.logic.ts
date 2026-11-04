/**
 * #892: the utilization report printed "NaN%".
 *
 * `utilization_rate` is scheduled-hours-over-available-hours, so a coach with
 * nothing scheduled divides zero by zero and the backend hands the report a
 * NaN. `Intl.NumberFormat.format(NaN)` renders the literal string "NaN%",
 * which reads as a bug in the money numbers next to it. Both percent columns
 * go through this one guard so a second silent NaN cannot reappear in the
 * other one.
 */
export function formatRatePercent(value: number | null | undefined): string {
  if (value === null || value === undefined || !Number.isFinite(value)) return "No data";
  return new Intl.NumberFormat("en-US", { style: "percent", maximumFractionDigits: 0 }).format(
    value,
  );
}
