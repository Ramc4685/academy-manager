"use client";

import { useState } from "react";
import { useSearchParams } from "next/navigation";

import { RegistrationsTab } from "@/components/admin/admissions/RegistrationsTab";
import { WaitlistTab } from "@/components/admin/admissions/WaitlistTab";
import { LevelUpsTab } from "@/components/admin/admissions/LevelUpsTab";

type AdmissionsTab = "registrations" | "waitlist" | "level-ups";

const TABS: { id: AdmissionsTab; label: string }[] = [
  { id: "registrations", label: "Registrations" },
  { id: "waitlist", label: "Waitlist" },
  { id: "level-ups", label: "Level-ups" },
];

function coerceTab(value: string | null): AdmissionsTab {
  return value && TABS.some((t) => t.id === value) ? (value as AdmissionsTab) : "registrations";
}

export default function AdminRegistrationsPage() {
  const searchParams = useSearchParams();
  const [tab, setTab] = useState<AdmissionsTab>(() => coerceTab(searchParams.get("tab")));

  return (
    <section data-testid="admin-registrations" className="space-y-6">
      <div>
        <h1 className="font-display text-2xl font-bold tracking-tight text-rally-ink">Admissions</h1>
        <p className="mt-0.5 text-sm text-rally-subtle">
          Pending registrations, session waitlists, and coach level-up recommendations
        </p>
      </div>

      <div role="tablist" aria-label="Admissions type" className="flex flex-wrap gap-1 rounded-xl bg-neutral-100 p-1 dark:bg-neutral-800">
        {TABS.map((t) => (
          <button
            key={t.id}
            type="button"
            role="tab"
            aria-selected={tab === t.id}
            onClick={() => setTab(t.id)}
            className="min-h-touch flex-1 rounded-lg px-3 text-sm font-semibold transition-all duration-150"
            style={
              tab === t.id
                ? { background: "white", color: "var(--rally-ink)", boxShadow: "0 1px 2px rgba(0,0,0,0.06)" }
                : { background: "transparent", color: "var(--rally-muted)" }
            }
          >
            {t.label}
          </button>
        ))}
      </div>

      {tab === "registrations" && <RegistrationsTab />}
      {tab === "waitlist" && <WaitlistTab />}
      {tab === "level-ups" && <LevelUpsTab />}
    </section>
  );
}
