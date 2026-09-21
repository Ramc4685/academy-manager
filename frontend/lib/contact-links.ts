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

export function whatsappHref(phone?: string | null): string | undefined {
  const digits = (phone ?? "").replace(/\D/g, "");
  return digits ? `https://wa.me/${digits}` : undefined;
}

export function mailtoHref(email?: string | null): string | undefined {
  const trimmed = (email ?? "").trim();
  return trimmed ? `mailto:${trimmed}` : undefined;
}
