"use client";

/**
 * Issue #865: ONE way to show a person's contact details, at every width.
 *
 * `ContactLinks` is the inline form for a header or a table cell;
 * `contactMenuItems` is the same three destinations as entries in a
 * `PhoneListRow`'s 44px overflow menu. Both read their hrefs from
 * `lib/contact-links.ts`, so a surface cannot end up with a tappable number in
 * one layout and plain text in the other — the defect this issue reported.
 *
 * Nothing renders for a missing value: a `tel:` on an empty string, or a
 * `wa.me` built from a formatted number, is a link to nowhere.
 */

import type { ReactNode } from "react";

import { mailtoHref, telHref, whatsappHref } from "@/lib/contact-links";

import type { MenuItem } from "./menu";

export interface ContactPoints {
  phone?: string | null;
  email?: string | null;
}

const LINK_CLASS =
  "rounded underline-offset-2 hover:underline focus:outline-none focus:ring-2 focus:ring-rally-cobalt-600";

export function ContactLinks({
  phone,
  email,
  name,
  fallback = null,
  className = "",
  ...rest
}: ContactPoints & {
  /** Whose details these are, for the links' accessible names. */
  name?: string | null;
  /** Rendered when there is neither a phone nor an email. */
  fallback?: ReactNode;
  className?: string;
  "data-testid"?: string;
}) {
  const tel = telHref(phone);
  const whatsapp = whatsappHref(phone);
  const mailto = mailtoHref(email);
  const who = name ? ` ${name}` : "";

  if (!tel && !whatsapp && !mailto) {
    return fallback === null ? null : (
      <div className={className} data-testid={rest["data-testid"]}>
        {fallback}
      </div>
    );
  }

  return (
    <div
      className={`flex flex-wrap items-center gap-x-3 gap-y-1 ${className}`}
      data-testid={rest["data-testid"]}
    >
      {mailto && (
        <a href={mailto} className={`${LINK_CLASS} break-all`} aria-label={`Email${who}`}>
          {email}
        </a>
      )}
      {tel && (
        <a href={tel} className={LINK_CLASS} aria-label={`Call${who}`}>
          {phone}
        </a>
      )}
      {whatsapp && (
        <a
          href={whatsapp}
          target="_blank"
          rel="noopener noreferrer"
          className={LINK_CLASS}
          aria-label={`WhatsApp${who}`}
        >
          WhatsApp
        </a>
      )}
    </div>
  );
}

/**
 * The same destinations for a row menu. Appended by `PhoneListRow` after the
 * caller's own actions, so a spec that clicks a row's first action still lands
 * where it did before (#857's helpers match items by exact label).
 */
export function contactMenuItems({ phone, email }: ContactPoints): MenuItem[] {
  const items: MenuItem[] = [];
  const tel = telHref(phone);
  const whatsapp = whatsappHref(phone);
  const mailto = mailtoHref(email);
  if (tel) items.push({ key: "contact-call", label: "Call", externalHref: tel });
  if (whatsapp) items.push({ key: "contact-whatsapp", label: "WhatsApp", externalHref: whatsapp });
  if (mailto) items.push({ key: "contact-email", label: "Email", externalHref: mailto });
  return items;
}
