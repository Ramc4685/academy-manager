"use client";

import { createContext, useContext } from "react";

import { setAmbientAcademyZone } from "./academy-time";

/**
 * S05: the academy's IANA zone for whichever shell is rendering (admin,
 * parent, coach). Each shell layout provides it from the academy read it
 * already makes; shared components read it here instead of guessing the
 * persona. Null until loaded (formatters then fall back to the browser zone
 * and still print a zone label).
 */
const AcademyZoneContext = createContext<string | null>(null);

export function AcademyZoneProvider({
  timezone,
  children,
}: {
  timezone: string | null | undefined;
  children: React.ReactNode;
}) {
  // Set during render so children formatting in this same pass see it. Only
  // in the browser: a server isolate serves many academies.
  if (typeof window !== "undefined") setAmbientAcademyZone(timezone ?? null);
  return (
    <AcademyZoneContext.Provider value={timezone ?? null}>{children}</AcademyZoneContext.Provider>
  );
}

export function useAcademyZone(): string | null {
  return useContext(AcademyZoneContext);
}
