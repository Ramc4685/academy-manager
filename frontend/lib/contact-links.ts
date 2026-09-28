/**
 * Issue #865: one place that turns a stored phone number or email address into
 * a link an admin can tap.
 *
 * Before this, the only `tel:` in admin was hand-written in the student header
 * (`app/(admin)/admin/students/[studentId]/page.tsx`); the family header and
 * both Users layouts printed the number as plain text, and nothing offered
 * WhatsApp at all.
 *
 * Each helper returns `undefined` rather than an empty-ish href, so a caller
 * that renders `href && <a …>` cannot produce a dead `tel:` or a
 * `https://wa.me/` that opens WhatsApp on nobody. `wa.me` is digits-only — a
 * link built from the display string "+1 (555) 010-1234" 404s — while `tel:`
 * keeps the raw text so the link and its label never disagree.
 */

export function telHref(phone?: string | null): string | undefined {
  const trimmed = (phone ?? "").trim();
  return trimmed ? `tel:${trimmed}` : undefined;
}

/** The calling code used when the academy has none: North America, every academy today. */
export const DEFAULT_PHONE_COUNTRY_CODE = "1";

const MIN_INTERNATIONAL_DIGITS = 8;
const NATIONAL_DIGITS = 10;

/**
 * Row 11: the same rules as the backend's `normalize_wa_number`
 * (`backend/v2/shared/comms/whatsapp.py`), so a Dues-page link and a people
 * page link for the same parent never disagree. Numbers are stored as typed;
 * anything that cannot be resolved to one international number gets no link
 * rather than a link to a stranger.
 *
 * `countryCode` is the academy's calling code (`phone_country_code` on the
 * admin academy view, derived from the academy's country). It is applied only
 * to a bare 10-digit national number; an explicit `+` or `00` always wins.
 */
export function whatsappHref(
  phone?: string | null,
  countryCode: string = DEFAULT_PHONE_COUNTRY_CODE,
): string | undefined {
  const text = (phone ?? "").trim();
  const digits = text.replace(/\D/g, "");
  if (!digits) return undefined;
  const number = waNumber(text, digits, countryCode || DEFAULT_PHONE_COUNTRY_CODE);
  return number ? `https://wa.me/${number}` : undefined;
}

function waNumber(text: string, digits: string, countryCode: string): string | undefined {
  // Explicitly international: trust the number as written.
  if (text.startsWith("+") || digits.startsWith("00")) {
    const international = digits.startsWith("00") ? digits.slice(2) : digits;
    return international.length >= MIN_INTERNATIONAL_DIGITS ? international : undefined;
  }
  // A leading trunk 0 says the number is NOT from the default country.
  if (digits.startsWith("0")) return undefined;
  if (digits.length === NATIONAL_DIGITS) return `${countryCode}${digits}`;
  if (digits.startsWith(countryCode) && digits.length === countryCode.length + NATIONAL_DIGITS) {
    return digits;
  }
  return undefined;
}

export function mailtoHref(email?: string | null): string | undefined {
  const trimmed = (email ?? "").trim();
  return trimmed ? `mailto:${trimmed}` : undefined;
}
