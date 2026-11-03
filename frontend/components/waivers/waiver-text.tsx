"use client";

import { useId } from "react";

import { parseWaiverSections } from "@/lib/waivers/sections";

const AUDIENCE_LABEL = { adult: "Participants 18 and over", minor: "Participants under 18" } as const;

/**
 * A waiver body split into its sections. Initialled sections show an
 * initials box when `needInitials` lists them, or the stored initials on a
 * signed copy (`signedInitials`).
 */
export function WaiverText({
  body,
  needInitials = [],
  initials = {},
  onInitials,
  signedInitials,
  className = "",
}: {
  body: string | null | undefined;
  needInitials?: ReadonlyArray<string>;
  initials?: Readonly<Record<string, string>>;
  onInitials?: (key: string, value: string) => void;
  signedInitials?: Readonly<Record<string, string>>;
  className?: string;
}) {
  const ids = useId();
  const sections = parseWaiverSections(body);
  if (sections.length === 0) {
    return <p className={`text-sm text-rally-muted ${className}`}>Waiver text is not available.</p>;
  }
  return (
    <div className={`space-y-4 text-sm leading-6 text-rally-ink ${className}`}>
      {sections.map((section) => (
        <section key={section.key} className="space-y-1.5">
          {section.heading && (
            <h3 className="font-semibold text-rally-ink">
              {section.heading}
              {section.audience !== "all" && (
                <span className="ml-2 text-xs font-normal text-rally-muted">
                  {AUDIENCE_LABEL[section.audience]}
                </span>
              )}
            </h3>
          )}
          {section.body && <p className="whitespace-pre-wrap">{section.body}</p>}
          {section.initials && signedInitials?.[section.key] && (
            <p className="text-xs font-semibold text-status-green-800">
              Initialled: {signedInitials[section.key]}
            </p>
          )}
          {section.initials && !signedInitials && needInitials.includes(section.key) && (
            <label
              className="flex items-center gap-2 text-xs font-medium text-rally-ink"
              htmlFor={`${ids}-${section.key}`}
            >
              Your initials
              <input
                id={`${ids}-${section.key}`}
                value={initials[section.key] ?? ""}
                onChange={(event) => onInitials?.(section.key, event.target.value.toUpperCase())}
                maxLength={4}
                autoComplete="off"
                aria-label={`Initials for ${section.heading ?? "this section"}`}
                className="min-h-touch w-20 rounded-md border border-rally-line px-2 text-center text-sm uppercase outline-none focus:border-rally-cobalt-600 focus:ring-2 focus:ring-rally-cobalt-600/15"
              />
            </label>
          )}
        </section>
      ))}
    </div>
  );
}
