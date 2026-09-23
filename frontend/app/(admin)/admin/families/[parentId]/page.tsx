"use client";

import {
  useCallback,
  useEffect,
  useRef,
  useState,
  type KeyboardEvent,
  type ReactNode,
} from "react";
import type { Route } from "next";
import Link from "next/link";
import { useParams, useRouter, useSearchParams } from "next/navigation";
import { useQuery } from "@tanstack/react-query";
import { ArrowLeft } from "lucide-react";

import { Card, Chip, Skeleton } from "@/components/ds";
import { ErrorNotice } from "@/components/ds/error-notice";
import { fetchAdminFamilyBilling, fetchFamilyRecord } from "@/lib/api/admin-families";
import { lifecycleLabel, lifecycleVariant } from "@/lib/format/lifecycle-copy";
import { queryKeys } from "@/lib/query/keys";

import { BillingTab } from "./BillingTab";
import { ChildDrawer } from "./ChildDrawer";
import { DetailsTab } from "./DetailsTab";
import { OverviewTab } from "./OverviewTab";
import { TimelinePanel } from "./TimelinePanel";
import {
  FAMILY_TABS,
  adjacentFamilyTab,
  childTriggerId,
  canonicalFamilyHref,
  familyTabQuery,
  overviewChildren,
  resolveFamilyTab,
  type FamilyTab,
} from "./family-record";

/**
 * The People CRM family record (spec §4, Lane A4): Overview, Details,
 * Billing and Timeline tabs on the existing /admin/families/[parentId] route,
 * with the tab in `?tab=` so a link to a family's Billing is a link to it.
 */
export default function FamilyRecordPage() {
  const params = useParams<{ parentId: string }>();
  const parentId = params.parentId;
  const router = useRouter();
  const searchParams = useSearchParams();
  const activeTab = resolveFamilyTab(searchParams.get("tab"));
  const tabRefs = useRef<Partial<Record<FamilyTab, HTMLButtonElement | null>>>({});
  const [openChildId, setOpenChildId] = useState<string | null>(null);

  const record = useQuery({
    queryKey: queryKeys.admin.familyRecord(parentId),
    queryFn: () => fetchFamilyRecord(parentId),
    retry: false,
  });
  // The same query (and cache entry) the Billing tab reads.
  const billing = useQuery({
    queryKey: queryKeys.admin.familyBilling(parentId),
    queryFn: () => fetchAdminFamilyBilling(parentId),
  });

  // Student pages link by the child's stored parent id, which may be an
  // alias (firebase uid, users _id). The record answers with the canonical
  // family id; swap the URL for it, keeping the tab, so every tab, cache key
  // and later link agree.
  const canonicalId = record.data?.family_id ?? record.data?.family.family_id;
  const query = searchParams.toString();
  useEffect(() => {
    const href = canonicalFamilyHref(parentId, canonicalId, query);
    if (href) router.replace(href as Route, { scroll: false });
  }, [canonicalId, parentId, query, router]);

  const setTab = (next: FamilyTab) => {
    router.replace(familyTabQuery(searchParams.toString(), next) as Route, { scroll: false });
  };

  const onTabKeyDown = (event: KeyboardEvent<HTMLButtonElement>) => {
    const next = adjacentFamilyTab(activeTab, event.key);
    if (!next) return;
    event.preventDefault();
    setTab(next);
    tabRefs.current[next]?.focus();
  };

  const family = record.data?.family ?? null;
  const kids = overviewChildren(family, billing.data?.students ?? []);
  const openChild = kids.find((k) => k.studentId === openChildId) ?? null;
  const title = family?.parent_name ?? billing.data?.parent.name ?? family?.email ?? "Family";

  const closeDrawer = useCallback(() => {
    const id = openChildId;
    setOpenChildId(null);
    // Focus goes back to the row that opened the drawer, never to <body>.
    if (id) requestAnimationFrame(() => document.getElementById(childTriggerId(id))?.focus());
  }, [openChildId]);

  return (
    <section data-testid="admin-family-record" className="space-y-4">
      <div className="space-y-2">
        <Link
          href={"/admin/families" as Route}
          className="inline-flex items-center gap-1.5 rounded text-sm text-rally-muted hover:text-rally-ink focus:outline-none focus:ring-2 focus:ring-rally-cobalt-600"
        >
          <ArrowLeft className="size-4" aria-hidden="true" />
          <span>Families</span>
        </Link>
        <div className="flex flex-wrap items-center gap-3">
          <h1
            className="font-display text-2xl font-semibold text-rally-ink"
            data-testid="family-record-name"
          >
            {title}
          </h1>
          {family && (
            <span data-testid="family-record-stage">
              <Chip variant={lifecycleVariant(family.stage)} label={lifecycleLabel(family.stage)} />
            </span>
          )}
        </div>
      </div>

      <div
        role="tablist"
        aria-label="Family record sections"
        data-testid="family-record-tabs"
        className="flex gap-1 overflow-x-auto border-b border-neutral-200"
      >
        {FAMILY_TABS.map((tab) => {
          const selected = activeTab === tab.id;
          return (
            <button
              key={tab.id}
              ref={(el) => {
                tabRefs.current[tab.id] = el;
              }}
              type="button"
              role="tab"
              id={`family-tab-${tab.id}`}
              aria-selected={selected}
              aria-controls={`family-tabpanel-${tab.id}`}
              tabIndex={selected ? 0 : -1}
              data-testid={`family-tab-${tab.id}`}
              className={`min-h-11 whitespace-nowrap border-b-2 px-3 py-2 text-sm font-medium transition-colors focus:outline-none focus:ring-2 focus:ring-rally-cobalt-600 ${
                selected
                  ? "border-rally-cobalt-600 text-rally-ink"
                  : "border-transparent text-rally-muted hover:text-rally-ink"
              }`}
              onClick={() => setTab(tab.id)}
              onKeyDown={onTabKeyDown}
            >
              {tab.label}
            </button>
          );
        })}
      </div>

      <div
        role="tabpanel"
        id={`family-tabpanel-${activeTab}`}
        aria-labelledby={`family-tab-${activeTab}`}
        className="min-w-0"
      >
        {record.isError && (activeTab === "overview" || activeTab === "details") && (
          <ErrorNotice
            testId="family-record-load-error"
            className="mb-4"
            message="Could not load this family's stage, balance and contact details. They are unknown, not blank."
            onRetry={() => void record.refetch()}
            retrying={record.isFetching}
          />
        )}
        {activeTab === "billing" ? (
          <BillingTab parentId={parentId} />
        ) : activeTab === "timeline" ? (
          <Loaded query={billing} what="the timeline">
            {billing.data && (
              <TimelinePanel timeline={billing.data.timeline} warnings={billing.data.warnings} />
            )}
          </Loaded>
        ) : record.isLoading && billing.isLoading ? (
          <Card p={20}>
            <Skeleton lines={4} />
          </Card>
        ) : activeTab === "details" ? (
          <DetailsTab family={family} parent={billing.data?.parent ?? null} kids={kids} />
        ) : (
          <OverviewTab
            record={record.data ?? null}
            billing={billing.data ?? null}
            kids={kids}
            onOpenChild={setOpenChildId}
          />
        )}
      </div>

      {openChild && <ChildDrawer child={openChild} onClose={closeDrawer} />}
    </section>
  );
}

function Loaded({
  query,
  what,
  children,
}: {
  query: { isLoading: boolean; isError: boolean; error: unknown; refetch: () => unknown };
  what: string;
  children: ReactNode;
}) {
  if (query.isLoading) {
    return (
      <Card p={20}>
        <Skeleton lines={6} />
      </Card>
    );
  }
  if (query.isError) {
    return (
      <Card p={20}>
        <p className="text-sm text-rally-ink" data-testid="family-record-error">
          Could not load {what}. {(query.error as Error | null)?.message ?? ""}
        </p>
      </Card>
    );
  }
  return <>{children}</>;
}
