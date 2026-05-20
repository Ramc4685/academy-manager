"use client";

export type SettingsPanelKey =
  | "academy"
  | "fees"
  | "gateway"
  | "notify"
  | "roles"
  | "branding"
  | "data";

export const SETTINGS_TABS: Array<{ key: SettingsPanelKey; label: string }> = [
  { key: "academy", label: "Academy" },
  { key: "fees", label: "Fees" },
  { key: "gateway", label: "Gateway" },
  { key: "notify", label: "Notify" },
  { key: "roles", label: "Roles" },
  { key: "branding", label: "Branding" },
  { key: "data", label: "Data" },
];

interface SettingsTabsProps {
  active: SettingsPanelKey;
  onChange: (key: SettingsPanelKey) => void;
}

export function SettingsTabs({ active, onChange }: SettingsTabsProps) {
  return (
    <div className="overflow-x-auto">
      <div className="inline-flex min-w-max gap-1 rounded-lg bg-rally-paper p-1">
        {SETTINGS_TABS.map((tab) => {
          const isActive = tab.key === active;
          return (
            <button
              key={tab.key}
              type="button"
              onClick={() => onChange(tab.key)}
              className={`rounded-md px-4 py-2 font-mono text-[10px] font-bold uppercase tracking-overline transition-colors ${
                isActive
                  ? "bg-blue-600 text-white"
                  : "text-rally-muted hover:bg-white hover:text-rally-ink"
              }`}
              aria-pressed={isActive}
            >
              {tab.label}
            </button>
          );
        })}
      </div>
    </div>
  );
}
