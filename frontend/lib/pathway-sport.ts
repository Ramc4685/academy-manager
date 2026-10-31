import type { ExternalSource } from "@/lib/api/curriculum";

export function titleCase(value: string): string {
  return value.length === 0 ? value : value[0].toUpperCase() + value.slice(1);
}

/** Row 13: the seed-badminton CTA and its placeholders only make sense for
 * a badminton academy. Sport comparison is case-insensitive and defaults to
 * badminton, mirroring the backend's read-time default. */
export function isBadmintonSport(sport: string | undefined): boolean {
  return (sport ?? "badminton").toLowerCase() === "badminton";
}

/** Row 13: badminton programs default new external refs to the BWF Shuttle
 * Time citation; every other sport defaults to an academy-authored source
 * (the placeholder BWF library isn't relevant to them). */
export function defaultExternalSourceForSport(isBadminton: boolean): ExternalSource {
  return isBadminton ? "BWF_SHUTTLE_TIME" : "ACADEMY_CUSTOM";
}

export function sourceTitlePlaceholder(isBadminton: boolean): string {
  return isBadminton ? "Source title (e.g. Shuttle Time Level 1)" : "Source title";
}
