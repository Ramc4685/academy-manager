"use client";

import { useEffect, useMemo } from "react";
import { usePathname, useRouter, useSearchParams } from "next/navigation";
import type { UrlObject } from "url";

import { AcademyPanel } from "@/components/admin/settings/academy-panel";
import { BillingRulesPanel } from "@/components/admin/settings/billing-rules-panel";
import { GatewayPanel } from "@/components/admin/settings/gateway-panel";
import { NotifyPanel } from "@/components/admin/settings/notify-panel";
import { SelfServicePanel } from "@/components/admin/settings/self-service-panel";
import { DeparturePolicyPanel } from "@/components/admin/settings/departure-policy-panel";
import { CurriculumPanel } from "@/components/admin/settings/curriculum-panel";
import { PublicPagePanel } from "@/components/admin/settings/public-page-panel";
import {
  OWNER_ONLY_SETTINGS_PANELS,
  RETIRED_SETTINGS_EXTERNAL_REDIRECTS,
  RETIRED_SETTINGS_PANELS,
  SETTINGS_TABS,
  SettingsTabs,
  type SettingsPanelKey,
} from "@/components/admin/settings/settings-tabs";
import { SettingsDirtyProvider } from "@/components/admin/settings/settings-dirty-context";
import { OwnerOnlyPanel, useIsOwner } from "@/components/admin/owner-context";

const validPanels = new Set<SettingsPanelKey>(SETTINGS_TABS.map((tab) => tab.key));

function coercePanel(value: string | null): SettingsPanelKey {
  if (!value) return "academy";
  if (validPanels.has(value as SettingsPanelKey)) return value as SettingsPanelKey;
  // A retired key (?panel=fees) redirects to its successor rather than
  // silently dropping the reader on the Academy tab.
  return RETIRED_SETTINGS_PANELS[value] ?? "academy";
}

export default function AdminSettingsPage() {
  const pathname = usePathname();
  const router = useRouter();
  const searchParams = useSearchParams();
  const rawPanel = searchParams.get("panel");
  const externalRedirect = rawPanel ? RETIRED_SETTINGS_EXTERNAL_REDIRECTS[rawPanel] : undefined;
  const active = coercePanel(rawPanel);
  const isOwner = useIsOwner();
  // Billing rules and Integrations are owner-only: the tabs disappear for admins
  // without the scope, and a deep link to one shows the owner-only panel.
  const tabs = isOwner
    ? SETTINGS_TABS
    : SETTINGS_TABS.filter((tab) => !OWNER_ONLY_SETTINGS_PANELS.has(tab.key));
  const ownerOnlyHere = !isOwner && OWNER_ONLY_SETTINGS_PANELS.has(active);

  const paramsString = searchParams.toString();
  const params = useMemo(() => new URLSearchParams(paramsString), [paramsString]);

  useEffect(() => {
    // ?panel=data / ?panel=roles moved to a whole other page (Settings
    // overhaul Lane D, PR 7): a real navigation, not an in-page panel swap.
    if (externalRedirect) {
      router.replace(externalRedirect(isOwner));
      return;
    }
    if (!searchParams.get("panel") || active !== searchParams.get("panel")) {
      const next = new URLSearchParams(params);
      next.set("panel", active);
      window.history.replaceState(null, "", `${pathname}?${next.toString()}`);
    }
  }, [active, externalRedirect, isOwner, params, pathname, router, searchParams]);

  if (externalRedirect) {
    return null;
  }

  function hrefForPanel(panel: SettingsPanelKey): UrlObject {
    const next = new URLSearchParams(params);
    next.set("panel", panel);
    // `program` and `stripe` belong to one panel's state; don't carry them
    // to a different tab.
    if (panel !== active) {
      next.delete("program");
      next.delete("stripe");
    }
    return {
      pathname,
      query: Object.fromEntries(next),
    };
  }

  return (
    // Only the active panel is mounted, so an unmount throws its draft away.
    // The provider lets the tab strip see that draft and confirm first (#863).
    <SettingsDirtyProvider>
      <section data-testid="admin-settings" className="space-y-6">
        <SettingsTabs active={active} hrefFor={hrefForPanel} tabs={tabs} />
        {ownerOnlyHere && <OwnerOnlyPanel />}
        {active === "academy" && <AcademyPanel />}
        {active === "billing-rules" && isOwner && <BillingRulesPanel />}
        {active === "integrations" && isOwner && <GatewayPanel />}
        {active === "notifications" && <NotifyPanel />}
        {active === "family-policies" && (
          <div className="space-y-6">
            <SelfServicePanel />
            <DeparturePolicyPanel />
          </div>
        )}
        {active === "public-page" && <PublicPagePanel />}
        {active === "curriculum" && <CurriculumPanel />}
      </section>
    </SettingsDirtyProvider>
  );
}
