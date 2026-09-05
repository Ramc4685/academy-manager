"use client";

import { useEffect, useMemo } from "react";
import { usePathname, useSearchParams } from "next/navigation";
import type { UrlObject } from "url";

import { AcademyPanel } from "@/components/admin/settings/academy-panel";
import { BrandingPanel } from "@/components/admin/settings/branding-panel";
import { DataPanel } from "@/components/admin/settings/data-panel";
import { FeesPanel } from "@/components/admin/settings/fees-panel";
import { InvoiceSchedulePanel } from "@/components/admin/settings/invoice-schedule-panel";
import { GatewayPanel } from "@/components/admin/settings/gateway-panel";
import { NotifyPanel } from "@/components/admin/settings/notify-panel";
import { RolesPanel } from "@/components/admin/settings/roles-panel";
import { SelfServicePanel } from "@/components/admin/settings/self-service-panel";
import { SessionTypesPanel } from "@/components/admin/settings/session-types-panel";
import {
  OWNER_ONLY_SETTINGS_PANELS,
  SETTINGS_TABS,
  SettingsTabs,
  type SettingsPanelKey,
} from "@/components/admin/settings/settings-tabs";
import { OwnerOnlyPanel, useIsOwner } from "@/components/admin/owner-context";

const validPanels = new Set<SettingsPanelKey>(SETTINGS_TABS.map((tab) => tab.key));

function coercePanel(value: string | null): SettingsPanelKey {
  return value && validPanels.has(value as SettingsPanelKey)
    ? (value as SettingsPanelKey)
    : "academy";
}

export default function AdminSettingsPage() {
  const pathname = usePathname();
  const searchParams = useSearchParams();
  const active = coercePanel(searchParams.get("panel"));
  const isOwner = useIsOwner();
  // Fees and Gateway are owner-only: the tabs disappear for admins without
  // the scope, and a deep link to one shows the owner-only panel instead.
  const tabs = isOwner
    ? SETTINGS_TABS
    : SETTINGS_TABS.filter((tab) => !OWNER_ONLY_SETTINGS_PANELS.has(tab.key));
  const ownerOnlyHere = !isOwner && OWNER_ONLY_SETTINGS_PANELS.has(active);

  const paramsString = searchParams.toString();
  const params = useMemo(() => new URLSearchParams(paramsString), [paramsString]);

  useEffect(() => {
    if (!searchParams.get("panel") || active !== searchParams.get("panel")) {
      const next = new URLSearchParams(params);
      next.set("panel", active);
      window.history.replaceState(null, "", `${pathname}?${next.toString()}`);
    }
  }, [active, params, pathname, searchParams]);

  function hrefForPanel(panel: SettingsPanelKey): UrlObject {
    const next = new URLSearchParams(params);
    next.set("panel", panel);
    return {
      pathname,
      query: Object.fromEntries(next),
    };
  }

  return (
    <section data-testid="admin-settings" className="space-y-6">
      <SettingsTabs active={active} hrefFor={hrefForPanel} tabs={tabs} />
      {ownerOnlyHere && <OwnerOnlyPanel />}
      {active === "academy" && <AcademyPanel />}
      {active === "fees" && isOwner && (
        <>
          <FeesPanel />
          <InvoiceSchedulePanel />
        </>
      )}
      {active === "gateway" && isOwner && <GatewayPanel />}
      {active === "notify" && <NotifyPanel />}
      {active === "roles" && <RolesPanel />}
      {active === "branding" && <BrandingPanel />}
      {active === "data" && <DataPanel />}
      {active === "self-service" && <SelfServicePanel />}
      {active === "session-types" && <SessionTypesPanel />}
    </section>
  );
}
