/**
 * The IANA timezone menu shared by every screen that lets a human choose an
 * academy's timezone (admin Settings → Academy, and platform tenant bootstrap).
 *
 * It lives here rather than inside one panel because the two screens must offer
 * the SAME list: a tenant bootstrapped with a zone the settings panel cannot
 * represent would show up as an "(current)" orphan entry, and a bootstrap form
 * that free-texts its zone is how `"UTC"` ended up stamped on a Chicago academy
 * in the first place — which then made every session that academy created read
 * back five hours early.
 */

export const TIMEZONE_OPTIONS: { group: string; zones: { value: string; label: string }[] }[] = [
  {
    group: "UTC",
    zones: [{ value: "UTC", label: "UTC" }],
  },
  {
    group: "United States & Canada",
    zones: [
      { value: "America/New_York", label: "Eastern Time — New York (ET)" },
      { value: "America/Chicago", label: "Central Time — Chicago (CT)" },
      { value: "America/Denver", label: "Mountain Time — Denver (MT)" },
      { value: "America/Phoenix", label: "Mountain Time — Phoenix (no DST)" },
      { value: "America/Los_Angeles", label: "Pacific Time — Los Angeles (PT)" },
      { value: "America/Anchorage", label: "Alaska Time (AKT)" },
      { value: "Pacific/Honolulu", label: "Hawaii Time (HST)" },
      { value: "America/Puerto_Rico", label: "Atlantic Time — Puerto Rico (AST)" },
      { value: "America/Toronto", label: "Eastern Time — Toronto (ET)" },
      { value: "America/Vancouver", label: "Pacific Time — Vancouver (PT)" },
    ],
  },
  {
    group: "Latin America",
    zones: [
      { value: "America/Mexico_City", label: "Mexico City (CST)" },
      { value: "America/Bogota", label: "Colombia Time (COT)" },
      { value: "America/Lima", label: "Peru Time (PET)" },
      { value: "America/Santiago", label: "Chile Time (CLT)" },
      { value: "America/Sao_Paulo", label: "Brasília Time (BRT)" },
      { value: "America/Argentina/Buenos_Aires", label: "Argentina Time (ART)" },
    ],
  },
  {
    group: "Europe",
    zones: [
      { value: "Europe/London", label: "London (GMT/BST)" },
      { value: "Europe/Dublin", label: "Dublin (GMT/IST)" },
      { value: "Europe/Lisbon", label: "Lisbon (WET/WEST)" },
      { value: "Europe/Paris", label: "Paris (CET/CEST)" },
      { value: "Europe/Berlin", label: "Berlin (CET/CEST)" },
      { value: "Europe/Amsterdam", label: "Amsterdam (CET/CEST)" },
      { value: "Europe/Madrid", label: "Madrid (CET/CEST)" },
      { value: "Europe/Rome", label: "Rome (CET/CEST)" },
      { value: "Europe/Stockholm", label: "Stockholm (CET/CEST)" },
      { value: "Europe/Helsinki", label: "Helsinki (EET/EEST)" },
      { value: "Europe/Athens", label: "Athens (EET/EEST)" },
      { value: "Europe/Moscow", label: "Moscow (MSK)" },
      { value: "Europe/Istanbul", label: "Istanbul (TRT)" },
    ],
  },
  {
    group: "Africa & Middle East",
    zones: [
      { value: "Africa/Cairo", label: "Cairo (EET)" },
      { value: "Africa/Johannesburg", label: "Johannesburg (SAST)" },
      { value: "Africa/Nairobi", label: "Nairobi (EAT)" },
      { value: "Asia/Dubai", label: "Dubai (GST)" },
      { value: "Asia/Riyadh", label: "Riyadh (AST)" },
    ],
  },
  {
    group: "Asia",
    zones: [
      { value: "Asia/Karachi", label: "Karachi (PKT)" },
      { value: "Asia/Kolkata", label: "India (IST)" },
      { value: "Asia/Colombo", label: "Sri Lanka (SLST)" },
      { value: "Asia/Dhaka", label: "Bangladesh (BST)" },
      { value: "Asia/Yangon", label: "Myanmar (MMT)" },
      { value: "Asia/Bangkok", label: "Bangkok (ICT)" },
      { value: "Asia/Singapore", label: "Singapore (SGT)" },
      { value: "Asia/Kuala_Lumpur", label: "Kuala Lumpur (MYT)" },
      { value: "Asia/Shanghai", label: "China Standard Time (CST)" },
      { value: "Asia/Hong_Kong", label: "Hong Kong (HKT)" },
      { value: "Asia/Taipei", label: "Taipei (CST)" },
      { value: "Asia/Tokyo", label: "Japan (JST)" },
      { value: "Asia/Seoul", label: "Korea (KST)" },
    ],
  },
  {
    group: "Australia & Pacific",
    zones: [
      { value: "Australia/Perth", label: "Perth (AWST)" },
      { value: "Australia/Darwin", label: "Darwin (ACST)" },
      { value: "Australia/Adelaide", label: "Adelaide (ACST/ACDT)" },
      { value: "Australia/Brisbane", label: "Brisbane (AEST)" },
      { value: "Australia/Sydney", label: "Sydney (AEST/AEDT)" },
      { value: "Australia/Melbourne", label: "Melbourne (AEST/AEDT)" },
      { value: "Pacific/Auckland", label: "Auckland (NZST/NZDT)" },
      { value: "Pacific/Fiji", label: "Fiji (FJT)" },
    ],
  },
];

/** Every selectable zone value, flattened — used to detect an unknown value. */
export const TIMEZONE_VALUES: string[] = TIMEZONE_OPTIONS.flatMap((group) =>
  group.zones.map((zone) => zone.value),
);
