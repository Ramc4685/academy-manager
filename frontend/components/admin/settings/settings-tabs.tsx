"use client";

import Link from "next/link";
import { useCallback, useEffect, useRef, useState } from "react";
import type { Route } from "next";
import type { UrlObject } from "url";

import { OverflowCue } from "@/components/ds/overflow-cue";

export type SettingsPanelKey =
  | "academy"
  | "billing-rules"
  | "integrations"
  | "notifications"
  | "family-policies"
  | "public-page"
  | "curriculum";

export const SETTINGS_TABS: Array<{ key: SettingsPanelKey; label: string }> = [
  { key: "academy", label: "Academy profile" },
  { key: "billing-rules", label: "Billing rules" },
  { key: "integrations", label: "Integrations" },
  { key: "notifications", label: "Notifications" },
  { key: "family-policies", label: "Family policies" },
  { key: "public-page", label: "Public page" },
  { key: "curriculum", label: "Curriculum" },
];

/**
 * Panels that change what the academy charges or where the money lands.
 * Owner-only: the BFF 404s their writes for anyone without the owner scope.
 */
export const OWNER_ONLY_SETTINGS_PANELS: ReadonlySet<SettingsPanelKey> = new Set<SettingsPanelKey>([
  "billing-rules",
  "integrations",
]);

/**
 * Retired panel keys that still resolve to another *panel within Settings*,
 * so an old bookmark lands somewhere sensible: `?panel=fees` renders
 * Billing rules (spec SS5). `?panel=branding` renders Academy profile
 * (Settings overhaul Phase 3 PR 9: Academy and Branding merged into one
 * tab, key stays "academy").
 */
export const RETIRED_SETTINGS_PANELS: Readonly<Record<string, SettingsPanelKey>> = {
  fees: "billing-rules",
  // Settings overhaul Phase 3 PR 10: Self-service was renamed Family
  // policies; `?panel=self-service` keeps working for old bookmarks.
  "self-service": "family-policies",
  branding: "academy",
  // Phase 3 PR 11: Gateway became Integrations and Notify became
  // Notifications. Stripe's return links still say `?panel=gateway&stripe=...`;
  // the page keeps the other query params when it maps the key, so the
  // connected/error banner still shows.
  gateway: "integrations",
  notify: "notifications",
};

/**
 * Retired panel keys whose successor lives on a *different page* (Settings
 * overhaul Lane D, PR 7): `?panel=data` and `?panel=roles` no longer render
 * inside Settings at all — the Data tab's exports duplicated the Reports
 * page, and the Roles tab duplicated the Staff page's role editor.
 *
 * `data`'s target is owner-only (Month close / Reports), so it takes the
 * current viewer's owner status and falls back to the default Settings
 * panel when they cannot reach it.
 */
export const RETIRED_SETTINGS_EXTERNAL_REDIRECTS: Readonly<
  Record<string, (isOwner: boolean) => Route>
> = {
  data: (isOwner) => (isOwner ? "/admin/reports" : "/admin/settings?panel=academy"),
  roles: () => "/admin/users",
  // Settings overhaul PR 11b: the price list is the Plans section of the
  // Pricing page under Money (owner-only; an admin sees its owner-only panel).
  "session-types": () => "/admin/pricing",
};

interface SettingsTabsProps {
  active: SettingsPanelKey;
  hrefFor: (key: SettingsPanelKey) => UrlObject;
  /** Tabs to render; defaults to every panel. */
  tabs?: ReadonlyArray<{ key: SettingsPanelKey; label: string }>;
}

export function SettingsTabs({ active, hrefFor, tabs = SETTINGS_TABS }: SettingsTabsProps) {
  const scrollerRef = useRef<HTMLDivElement | null>(null);
  const activeRef = useRef<HTMLAnchorElement | null>(null);
  const [overflow, setOverflow] = useState({ left: false, right: false });

  const syncOverflow = useCallback(() => {
    const el = scrollerRef.current;
    if (!el) return;
    setOverflow((prev) => {
      const left = el.scrollLeft > 1;
      const right = el.scrollLeft + el.clientWidth < el.scrollWidth - 1;
      return prev.left === left && prev.right === right ? prev : { left, right };
    });
  }, []);

  // Ten tabs never fit a phone: without this a deep link (or a guarded
  // switch) could leave the active tab scrolled off the strip with no hint
  // that it exists (#863).
  useEffect(() => {
    activeRef.current?.scrollIntoView({ inline: "center", block: "nearest" });
    syncOverflow();
  }, [active, tabs, syncOverflow]);

  useEffect(() => {
    window.addEventListener("resize", syncOverflow);
    return () => window.removeEventListener("resize", syncOverflow);
  }, [syncOverflow]);

  return (
    <div className="relative">
      <div
        ref={scrollerRef}
        onScroll={syncOverflow}
        className="snap-x snap-mandatory overflow-x-auto"
      >
        <div className="inline-flex min-w-max gap-1 rounded-lg bg-rally-paper p-1">
          {tabs.map((tab) => {
            const isActive = tab.key === active;
            return (
              <Link
                key={tab.key}
                ref={isActive ? activeRef : undefined}
                href={hrefFor(tab.key)}
                replace
                scroll={false}
                // #893: the shell-wide guard intercepts this click when a
                // panel holds unsaved edits and shows the DS dialog; the
                // attribute keeps its navigation a scroll-free replace, so
                // Back still leaves settings instead of walking the panels.
                data-unsaved-guard-nav="replace"
                className={`inline-flex min-h-11 snap-start items-center rounded-md px-4 py-3 font-mono text-[10px] font-bold uppercase tracking-overline transition-colors ${
                  isActive
                    ? "bg-blue-600 text-white"
                    : "text-rally-muted hover:bg-white hover:text-rally-ink"
                }`}
                aria-current={isActive ? "page" : undefined}
              >
                {tab.label}
              </Link>
            );
          })}
        </div>
      </div>
      {/* UI-7: fade plus chevron, the same cue as the People filter rows. */}
      {overflow.left && <OverflowCue side="left" testId="settings-tabs-more-left" />}
      {overflow.right && <OverflowCue side="right" testId="settings-tabs-more-right" />}
    </div>
  );
}
