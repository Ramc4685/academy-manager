"use client";

/**
 * The admin Inbox (issue #776).
 *
 * Admissions and Requests used to be two routes with eight uncounted tabs
 * between them, so "is anything waiting for me?" could only be answered by
 * opening all eight. This is one route, every tab carries its pending count,
 * and the tab that opens first is the first queue that actually has work.
 */

import { useMemo, useState } from "react";
import { useSearchParams } from "next/navigation";
import { useQuery } from "@tanstack/react-query";

import { RegistrationsTab } from "@/components/admin/admissions/RegistrationsTab";
import { WaitlistTab } from "@/components/admin/admissions/WaitlistTab";
import { LevelUpsTab } from "@/components/admin/admissions/LevelUpsTab";
import {
  AbsencesTab,
  CancellationsTab,
  MakeupsTab,
  TrialsTab,
} from "@/components/admin/requests/request-queues";
import { PausesTab } from "@/components/admin/requests/PausesTab";
import { getAdminInboxCounts } from "@/lib/api/admin";
import { queryKeys } from "@/lib/query/keys";
import {
  INBOX_TABS,
  defaultInboxTab,
  isInboxTab,
  type InboxTab,
} from "@/lib/admin-inbox-tabs";

export default function AdminInboxPage() {
  const searchParams = useSearchParams();
  const requested = searchParams.get("tab");
  const countsQuery = useQuery({
    queryKey: queryKeys.admin.inboxCounts(),
    queryFn: getAdminInboxCounts,
  });
  const counts = countsQuery.data?.counts;

  const [picked, setPicked] = useState<InboxTab | null>(() =>
    isInboxTab(requested) ? requested : null,
  );
  // Until the counts land there is nothing to pick by, so the resolved tab is
  // derived rather than stored: a click pins `picked` and stops the counts
  // from moving the admin off the tab they are reading.
  const tab = useMemo(
    () => picked ?? defaultInboxTab(requested, counts),
    [picked, requested, counts],
  );

  return (
    <section data-testid="admin-inbox" className="space-y-6">
      <div>
        <h1 className="font-display text-2xl font-bold tracking-tight text-rally-ink">Inbox</h1>
        <p className="mt-0.5 text-sm text-rally-subtle">
          Everything waiting on a decision: registrations, waitlists, level-ups, and parent
          requests
        </p>
      </div>

      <div
        role="tablist"
        aria-label="Inbox queue"
        className="flex flex-wrap gap-1 rounded-xl bg-neutral-100 p-1 dark:bg-neutral-800"
      >
        {INBOX_TABS.map((t) => {
          const count = counts?.[t.id] ?? 0;
          return (
            <button
              key={t.id}
              type="button"
              role="tab"
              data-testid={`admin-inbox-tab-${t.id}`}
              aria-selected={tab === t.id}
              onClick={() => setPicked(t.id)}
              className="min-h-touch flex-1 rounded-lg px-3 text-sm font-semibold transition-all duration-150"
              style={
                tab === t.id
                  ? {
                      background: "white",
                      color: "var(--rally-ink)",
                      boxShadow: "0 1px 2px rgba(0,0,0,0.06)",
                    }
                  : { background: "transparent", color: "var(--rally-muted)" }
              }
            >
              {t.label}
              {count > 0 && (
                <span
                  data-testid={`admin-inbox-count-${t.id}`}
                  className="ml-1.5 rounded-full bg-rally-cobalt px-1.5 py-0.5 font-mono text-[10px] font-bold text-white"
                >
                  {count}
                </span>
              )}
            </button>
          );
        })}
      </div>

      {tab === "registrations" && <RegistrationsTab />}
      {tab === "waitlist" && <WaitlistTab />}
      {tab === "level-ups" && <LevelUpsTab />}
      {tab === "makeups" && <MakeupsTab />}
      {tab === "trials" && <TrialsTab />}
      {tab === "absences" && <AbsencesTab />}
      {tab === "cancellations" && <CancellationsTab />}
      {tab === "pauses" && <PausesTab />}
    </section>
  );
}
