"use client";

import type { Route } from "next";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { useCallback, useEffect, useRef, useState, type MouseEvent } from "react";
import type { UrlObject } from "url";

import { useSettingsDirty } from "@/components/admin/settings/settings-dirty-context";

export type SettingsPanelKey =
  | "academy"
  | "billing-rules"
  | "gateway"
  | "notify"
  | "roles"
  | "branding"
  | "data"
  | "self-service"
  | "session-types";

export const SETTINGS_TABS: Array<{ key: SettingsPanelKey; label: string }> = [
  { key: "academy", label: "Academy" },
  { key: "billing-rules", label: "Billing rules" },
  { key: "gateway", label: "Gateway" },
  { key: "notify", label: "Notify" },
  { key: "roles", label: "Roles" },
  { key: "branding", label: "Branding" },
  { key: "data", label: "Data" },
  { key: "self-service", label: "Self-service" },
  { key: "session-types", label: "Session types" },
];

/**
 * Panels that change what the academy charges or where the money lands.
 * Owner-only: the BFF 404s their writes for anyone without the owner scope.
 */
export const OWNER_ONLY_SETTINGS_PANELS: ReadonlySet<SettingsPanelKey> = new Set<SettingsPanelKey>([
  "billing-rules",
  "gateway",
]);

/**
 * Retired panel keys that still resolve, so an old bookmark lands somewhere
 * sensible: `?panel=fees` renders Billing rules (spec SS5).
 */
export const RETIRED_SETTINGS_PANELS: Readonly<Record<string, SettingsPanelKey>> = {
  fees: "billing-rules",
};

interface SettingsTabsProps {
  active: SettingsPanelKey;
  hrefFor: (key: SettingsPanelKey) => UrlObject;
  /** Tabs to render; defaults to every panel. */
  tabs?: ReadonlyArray<{ key: SettingsPanelKey; label: string }>;
}

const LEAVE_UNSAVED_PROMPT =
  "You have unsaved changes on this tab. Leave without saving?";

export function SettingsTabs({ active, hrefFor, tabs = SETTINGS_TABS }: SettingsTabsProps) {
  const router = useRouter();
  const { dirty } = useSettingsDirty();
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

  // Nine tabs never fit a phone: without this a deep link (or a guarded
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

  function onTabClick(event: MouseEvent<HTMLAnchorElement>, key: SettingsPanelKey) {
    if (!dirty || key === active) return;
    // Scoped to the tab strip on purpose: a global router/beforeunload guard
    // would also fire on unrelated navigation out of the settings page.
    const href = event.currentTarget.getAttribute("href");
    event.preventDefault();
    if (!window.confirm(LEAVE_UNSAVED_PROMPT)) return;
    if (href) router.replace(href as Route, { scroll: false });
  }

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
                onClick={(event) => onTabClick(event, tab.key)}
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
      {overflow.left && (
        <div
          aria-hidden
          className="pointer-events-none absolute inset-y-0 left-0 w-6 rounded-l-lg bg-gradient-to-r from-white to-transparent"
        />
      )}
      {overflow.right && (
        <div
          aria-hidden
          className="pointer-events-none absolute inset-y-0 right-0 w-6 rounded-r-lg bg-gradient-to-l from-white to-transparent"
        />
      )}
    </div>
  );
}
