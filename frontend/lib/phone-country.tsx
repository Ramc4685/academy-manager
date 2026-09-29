"use client";

/**
 * Row 11: the academy's phone calling code, for the WhatsApp links every
 * admin people surface builds (`lib/contact-links.ts`).
 *
 * The admin shell already loads the academy (`getAdminAcademy`), whose
 * read-only `phone_country_code` the backend derives from the academy's
 * country. The shell provides it once here instead of every page threading
 * it through to `ContactLinks`. Outside a provider (tests, other shells) the
 * default is "1", the code every academy has today.
 */

import { createContext, useContext, type ReactNode } from "react";

import { DEFAULT_PHONE_COUNTRY_CODE } from "./contact-links";

const PhoneCountryContext = createContext<string>(DEFAULT_PHONE_COUNTRY_CODE);

export function PhoneCountryProvider({
  countryCode,
  children,
}: {
  /** `phone_country_code` from the academy view; unset while it loads. */
  countryCode?: string | null;
  children: ReactNode;
}) {
  return (
    <PhoneCountryContext.Provider value={countryCode || DEFAULT_PHONE_COUNTRY_CODE}>
      {children}
    </PhoneCountryContext.Provider>
  );
}

export function usePhoneCountryCode(): string {
  return useContext(PhoneCountryContext);
}
