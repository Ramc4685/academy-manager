"use client";

import Link from "next/link";
import type { UrlObject } from "url";

export type SettingsPanelKey =
  | "academy"
  | "fees"
  | "gateway"
  | "notify"
  | "roles"
  | "branding"
  | "data"
  | "self-service";

export const SETTINGS_TABS: Array<{ key: SettingsPanelKey; label: string }> = [
  { key: "academy", label: "Academy" },
  { key: "fees", label: "Fees" },
  { key: "gateway", label: "Gateway" },
  { key: "notify", label: "Notify" },
  { key: "roles", label: "Roles" },
  { key: "branding", label: "Branding" },
  { key: "data", label: "Data" },
  { key: "self-service", label: "Self-service" },
];

interface SettingsTabsProps {
  active: SettingsPanelKey;
  hrefFor: (key: SettingsPanelKey) => UrlObject;
}

export function SettingsTabs({ active, hrefFor }: SettingsTabsProps) {
  return (
    <div className="overflow-x-auto">
      <div className="inline-flex min-w-max gap-1 rounded-lg bg-rally-paper p-1">
        {SETTINGS_TABS.map((tab) => {
          const isActive = tab.key === active;
          return (
            <Link
              key={tab.key}
              href={hrefFor(tab.key)}
              replace
              scroll={false}
              className={`rounded-md px-4 py-2 font-mono text-[10px] font-bold uppercase tracking-overline transition-colors ${
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
  );
}
