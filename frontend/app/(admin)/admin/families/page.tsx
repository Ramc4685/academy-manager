"use client";

/**
 * Admin Families: the People CRM Families view (engineering-spec §3.2).
 *
 * One row per family record from the family index (`GET /admin/families`):
 * the parent and how to reach them, each child with their lifecycle chip,
 * the rolled-up family stage, card and login state, and the balance when the
 * server says this caller may see money. Scope tiles come from
 * `GET /admin/families/summary`, over the unfiltered index.
 *
 * Filtering, sorting and paging are the backend's; this page only keeps the
 * filter state in the URL and renders what comes back. Money is never
 * computed here: a `null` money block (or `money_visible: false`) hides the
 * amount, it never becomes a zero. Front desk (`money_view: "flag"`, L2b)
 * gets an "Owes money" flag from the server and never an amount; the owner
 * can preview that with "Viewing as". Actions (invites, charging, autopay) live
 * on the per-family page (`/admin/families/[parentId]`), except the one bulk
 * invite #897 put on this list and the CSV import (roadmap L8b,
 * `FamilyImportPanel`).
 */

import { Suspense, useCallback, useEffect, useMemo, useRef, useState } from "react";
import type { Route } from "next";
import Link from "next/link";
import { usePathname, useRouter, useSearchParams } from "next/navigation";
import { useInfiniteQuery, useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { ArrowDown, ArrowUp, ArrowUpDown, Mail } from "lucide-react";

import {
  fetchBillingSetup,
  inviteBillingSetupParent,
  listAdminSessions,
  type BillingSetupRow,
} from "@/lib/api/admin";
import {
  fetchFamilyIndex,
  fetchFamilyIndexSummary,
  type FamilyIndexChild,
  type FamilyIndexRow,
  type FamilyIndexSort,
  type FamilyMoneyView,
  type FamilyScope,
} from "@/lib/api/admin-families";
import { effectiveMoneyView, familyMoneyDisplay, serverMoneyView } from "@/lib/family-money-view";
import { FamilyMoneyCell } from "@/components/admin/family-money";
import { ViewingAsToggle, useViewingAs } from "@/components/admin/viewing-as";
import { queryKeys } from "@/lib/query/keys";
import { cardChip, loginChip, loginStateFromRegistration } from "@/lib/people-status";
import { lifecycleLabel, lifecycleVariant } from "@/lib/format/lifecycle-copy";
import {
  FALLBACK_PRESETS,
  ariaSort,
  classOptions,
  clearFilterChips,
  familyClasses,
  familyDisplayName,
  familyHref,
  familyResultRows,
  familiesCountLabel,
  hasFilterChips,
  isPresetActive,
  nextSort,
  parseFamilyIndexState,
  studentHref,
  toFamilyIndexParams,
  togglePreset,
  writeFamilyIndexState,
  type FamilyIndexState,
  type FamilyResultRow,
} from "@/lib/admin/family-index-view";
import { useIsPhone } from "@/lib/use-is-phone";

import { Button } from "@/components/ds/button";
import { Card } from "@/components/ds/card";
import { Chip } from "@/components/ds/chip";
import { ContactLinks } from "@/components/ds/contact-links";
import { ErrorNotice } from "@/components/ds/error-notice";
import { PhoneList, PhoneListRow } from "@/components/ds/phone-row";
import { BigNum, Overline } from "@/components/ds/typography";
import {
  FilterBar,
  FilterChip,
  ListToolbar,
  ToolbarSearch,
} from "@/components/ds/list-toolbar";
import { Th } from "@/components/ds/dialog-chrome";
import { ConfirmActionDialog } from "@/components/admin/confirm-action-dialog";
import { PipelineBoard } from "@/components/admin/people/pipeline-board";

import { FamilyImportPanel } from "./FamilyImportPanel";

const PAGE_SIZE = 50;
/** Bounded walk of the Billing Setup pages for the bulk invite's recipients. */
const MAX_INVITE_PAGES = 20;

function formatCents(cents: number): string {
  return new Intl.NumberFormat("en-US", { style: "currency", currency: "USD" }).format(
    cents / 100,
  );
}

const TILES: { scope: FamilyScope; label: string; caption: string; accent: string }[] = [
  { scope: "active", label: "Active", caption: "At least one child attending", accent: "#10b981" },
  { scope: "leaving", label: "Leaving", caption: "At risk, on hold, paused or ending", accent: "#f59e0b" },
  { scope: "left", label: "Left", caption: "No child on the books", accent: "#64748b" },
];

const WARNING_COPY: Record<string, string> = {
  money_unavailable: "Balances could not be read just now. They show as unknown, not zero.",
  classes_unavailable: "Class names could not be read just now, so the class chips may be missing.",
};

export default function FamiliesPage() {
  // `useSearchParams` needs a Suspense boundary for the static build.
  return (
    <Suspense fallback={<div className="flex flex-col gap-6" />}>
      <PeopleViews />
    </Suspense>
  );
}

/**
 * People CRM views on one route (spec §1: "Families, Pipeline ... are views
 * over the same family index"). `?view=pipeline` is the Pipeline board (L3b,
 * deep link `?view=pipeline&stage=trial_booked`); anything else is Families.
 */
function PeopleViews() {
  const searchParams = useSearchParams();
  const pipeline = searchParams.get("view") === "pipeline";
  return (
    <div className="flex flex-col gap-4">
      <nav aria-label="People views" data-testid="admin-people-views">
        <ul className="flex gap-2">
          {(
            [
              { href: "/admin/families", label: "Families", current: !pipeline, id: "families" },
              {
                href: "/admin/families?view=pipeline",
                label: "Pipeline",
                current: pipeline,
                id: "pipeline",
              },
            ] as const
          ).map((item) => (
            <li key={item.id}>
              <Link
                href={item.href as Route}
                aria-current={item.current ? "page" : undefined}
                data-testid={`admin-people-view-${item.id}`}
                className={`inline-flex h-9 items-center rounded-full border px-4 text-sm font-semibold focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-rally-cobalt-600 ${
                  item.current
                    ? "border-rally-ink bg-rally-ink text-white"
                    : "border-rally-line bg-white text-rally-base hover:bg-rally-paper"
                }`}
              >
                {item.label}
              </Link>
            </li>
          ))}
        </ul>
      </nav>
      {pipeline ? <PipelineBoard initialStage={searchParams.get("stage")} /> : <FamiliesView />}
    </div>
  );
}

function FamiliesView() {
  const router = useRouter();
  const pathname = usePathname();
  const searchParams = useSearchParams();
  const queryClient = useQueryClient();

  const urlKey = searchParams.toString();
  const state = useMemo(() => parseFamilyIndexState(new URLSearchParams(urlKey)), [urlKey]);

  // The URL is the filter state (spec §3.2: "kept in the URL"). Only a click
  // or a settled search writes it; landing on the page never rewrites it, so
  // `/admin/families?view=families` from the /admin/parents redirect stays.
  const setState = useCallback(
    (next: FamilyIndexState) => {
      const query = writeFamilyIndexState(new URLSearchParams(urlKey), next).toString();
      if (query === urlKey) return;
      router.replace(`${pathname}${query ? `?${query}` : ""}` as Route, { scroll: false });
    },
    [pathname, router, urlKey],
  );

  const [q, setQ] = useState(state.q);
  const stateRef = useRef(state);
  const setStateRef = useRef(setState);
  useEffect(() => {
    stateRef.current = state;
    setStateRef.current = setState;
  });
  useEffect(() => {
    const timer = window.setTimeout(() => {
      const current = stateRef.current;
      if (q.trim() !== current.q.trim()) setStateRef.current({ ...current, q });
    }, 300);
    return () => window.clearTimeout(timer);
  }, [q]);

  const params = useMemo(() => toFamilyIndexParams(state, 1, PAGE_SIZE), [state]);
  const indexQuery = useInfiniteQuery({
    queryKey: queryKeys.admin.familyIndex({ ...params, page: undefined }),
    queryFn: ({ pageParam }) => fetchFamilyIndex({ ...params, page: pageParam }),
    initialPageParam: 1,
    getNextPageParam: (last) =>
      last.page * last.page_size < last.total ? last.page + 1 : undefined,
    retry: false,
  });
  const summaryQuery = useQuery({
    queryKey: queryKeys.admin.familyIndexSummary(),
    queryFn: fetchFamilyIndexSummary,
    retry: false,
  });
  const sessionsQuery = useQuery({
    queryKey: queryKeys.admin.sessions("upcoming"),
    queryFn: () => listAdminSessions(undefined, { window: "upcoming" }),
    retry: false,
  });

  const firstPage = indexQuery.data?.pages[0];
  const families = useMemo(
    () => indexQuery.data?.pages.flatMap((page) => page.families ?? []) ?? [],
    [indexQuery.data],
  );
  const [viewingAs] = useViewingAs();
  const moneyView: FamilyMoneyView = firstPage
    ? effectiveMoneyView(serverMoneyView(firstPage), viewingAs)
    : "none";
  // Sorting and the Overdue chip work on amounts, so only amount viewers get them.
  const moneyVisible = moneyView === "amounts";
  const searching = state.q.trim().length > 0;
  const rows = useMemo(() => familyResultRows(families, searching), [families, searching]);
  const warnings = useMemo(
    () =>
      Array.from(
        new Set([...(firstPage?.warnings ?? []), ...(summaryQuery.data?.warnings ?? [])]),
      ),
    [firstPage, summaryQuery.data],
  );

  const summary = summaryQuery.data;
  // A money preset only ever arrives from a server that cleared this caller
  // for money; without the summary the chips fall back to the no-money set.
  const presets = (summary?.presets ?? FALLBACK_PRESETS).filter(
    (preset) => moneyVisible || !preset.money,
  );
  const classes = useMemo(
    () => classOptions(sessionsQuery.data?.sessions ?? [], families, state.classId),
    [sessionsQuery.data, families, state.classId],
  );

  const onSort = (column: FamilyIndexSort) => setState(nextSort(state, column, moneyVisible));
  const refreshAll = () => {
    void queryClient.invalidateQueries({ queryKey: queryKeys.admin.families() });
  };

  return (
    <div className="flex flex-col gap-6" data-testid="admin-families">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <p className="text-sm text-rally-muted">
          Families · every family, their children and where they stand; open one for the full
          picture
        </p>
        <ViewingAsToggle />
      </div>

      {summaryQuery.isError ? (
        <ErrorNotice
          testId="admin-families-summary-error"
          message="Could not load the family counts. They are unknown, not zero."
          onRetry={() => void summaryQuery.refetch()}
          retrying={summaryQuery.isFetching}
        />
      ) : null}

      <div className="grid grid-cols-2 gap-4 sm:grid-cols-4" data-testid="admin-families-tiles">
        <Card p={20} accent="#2563eb">
          <Overline>Families</Overline>
          <BigNum>
            <span data-testid="admin-families-tile-total">{summary?.total_families ?? "—"}</span>
          </BigNum>
          <p className="mt-1 text-[11px] text-rally-subtle">Everyone on record</p>
        </Card>
        {TILES.map((tile) => (
          <Card key={tile.scope} p={20} accent={tile.accent}>
            <Overline>{tile.label}</Overline>
            <BigNum>
              <span data-testid={`admin-families-tile-${tile.scope}`}>
                {summary?.tiles[tile.scope] ?? "—"}
              </span>
            </BigNum>
            <p className="mt-1 text-[11px] text-rally-subtle">{tile.caption}</p>
          </Card>
        ))}
      </div>

      <BulkInviteNotInvited onInvited={refreshAll} />

      <FamilyImportPanel onImported={refreshAll} />

      <Card p={0}>
        <ListToolbar>
          {/* Presets are toggles applied on click (aria-pressed), never a
              select that commits on change (critique P1). */}
          <FilterBar label="Family views" testId="admin-families-filters">
            <FilterChip
              active={!hasFilterChips(state)}
              label="All"
              count={summary?.total_families ?? null}
              testId="admin-families-filter-all"
              onClick={() => setState(clearFilterChips(state))}
            />
            {presets.map((preset) => {
              const scope = preset.params.scope as FamilyScope | undefined;
              const onlyScope = scope && Object.keys(preset.params).length === 1;
              return (
                <FilterChip
                  key={preset.id}
                  active={isPresetActive(preset, state)}
                  label={preset.label}
                  count={
                    onlyScope
                      ? (summary?.tiles[scope] ?? null)
                      : (summary?.preset_counts?.[preset.id] ?? null)
                  }
                  testId={`admin-families-preset-${preset.id}`}
                  countTestId={`admin-families-preset-${preset.id}-count`}
                  onClick={() => setState(togglePreset(state, preset))}
                />
              );
            })}
          </FilterBar>

          <div className="flex flex-wrap items-center gap-2 lg:justify-end">
            <label htmlFor="admin-families-class" className="text-sm text-rally-muted">
              Class
            </label>
            <select
              id="admin-families-class"
              data-testid="admin-families-class"
              value={state.classId ?? ""}
              onChange={(e) => setState({ ...state, classId: e.target.value || null })}
              className="h-10 max-w-[14rem] rounded-md border border-neutral-200 bg-white px-2 font-body text-sm text-rally-base"
            >
              <option value="">All classes</option>
              {classes.map((option) => (
                <option key={option.value} value={option.value}>
                  {option.label}
                </option>
              ))}
            </select>
            <ToolbarSearch
              id="admin-families-search"
              label="Search families"
              value={q}
              onChange={setQ}
              placeholder="Search parent, child, email or phone"
              busy={indexQuery.isFetching && !indexQuery.isFetchingNextPage}
              busyLabel="Refreshing families"
            />
          </div>
        </ListToolbar>

        {warnings.map((code) => (
          <p
            key={code}
            role="status"
            data-testid={`admin-families-warning-${code}`}
            className="border-b border-rally-line bg-status-amber-50 px-5 py-2 text-sm text-status-amber-800"
          >
            {WARNING_COPY[code] ?? "Part of this list could not be read just now."}
          </p>
        ))}

        {indexQuery.isLoading ? (
          <div className="p-8 text-center text-sm text-rally-muted">Loading…</div>
        ) : indexQuery.isError ? (
          <ErrorNotice
            testId="admin-families-error"
            className="m-5"
            message="Could not load families. The list is unknown, not empty."
            onRetry={() => void indexQuery.refetch()}
            retrying={indexQuery.isFetching}
          />
        ) : (
          <>
            {/* A stable anchor: it stays put whatever the filters do to the rows. */}
            <h2
              id="admin-families-results"
              tabIndex={-1}
              data-testid="admin-families-count"
              aria-live="polite"
              className="px-5 pt-4 text-sm font-semibold text-rally-base focus:outline-none"
            >
              {familiesCountLabel(firstPage?.total ?? 0, searching)}
            </h2>
            {rows.length === 0 ? (
              <div className="p-8 text-center text-sm text-rally-muted">
                {searching || hasFilterChips(state) || state.classId
                  ? "No families match these filters."
                  : "No families yet."}
              </div>
            ) : (
              <FamiliesList
                rows={rows}
                moneyView={moneyView}
                state={state}
                onSort={onSort}
              />
            )}
          </>
        )}
        {indexQuery.hasNextPage && (
          <div className="border-t border-rally-line p-4 text-center">
            <Button
              size="sm"
              variant="secondary"
              onClick={() => indexQuery.fetchNextPage()}
              disabled={indexQuery.isFetchingNextPage}
            >
              {indexQuery.isFetchingNextPage ? "Loading…" : "Load more families"}
            </Button>
          </div>
        )}
      </Card>
    </div>
  );
}

/**
 * #897: the one bulk action this list carries. Recipients come from the
 * Billing Setup read the invite endpoint itself resolves against (the family
 * index keys families by canonical user id, which is not always the id the
 * invite endpoint knows), walked page by page with a hard cap.
 */
function BulkInviteNotInvited({ onInvited }: { onInvited: () => void }) {
  const notInvitedQuery = useQuery({
    queryKey: queryKeys.admin.familiesNotInvited(),
    queryFn: async () => {
      const rows: BillingSetupRow[] = [];
      let cursor: string | undefined;
      for (let i = 0; i < MAX_INVITE_PAGES; i += 1) {
        const page = await fetchBillingSetup({ status: "no_account", cursor });
        rows.push(...(page.rows ?? []));
        if (!page.next_cursor) return { rows, complete: true };
        cursor = page.next_cursor;
      }
      return { rows, complete: false };
    },
    retry: false,
  });
  const notInvited = useMemo(
    () =>
      (notInvitedQuery.data?.rows ?? []).filter((row) => row.registration_state === "no_account"),
    [notInvitedQuery.data],
  );
  const [bulkOpen, setBulkOpen] = useState(false);
  const [bulkNote, setBulkNote] = useState<string | null>(null);

  const bulkInvite = useMutation({
    // One request per family through the existing per-family endpoint: there
    // is no bulk invite for parents who already exist.
    mutationFn: async (parentIds: string[]) => {
      let sent = 0;
      let failed = 0;
      for (const parentId of parentIds) {
        try {
          const result = await inviteBillingSetupParent(parentId);
          if (result.ok) sent += 1;
          else failed += 1;
        } catch {
          failed += 1;
        }
      }
      return { sent, failed };
    },
    onSuccess: ({ sent, failed }) => {
      setBulkOpen(false);
      setBulkNote(
        failed === 0
          ? `Invited ${sent} ${sent === 1 ? "family" : "families"}.`
          : `Invited ${sent}; ${failed} could not be invited.`,
      );
      void notInvitedQuery.refetch();
      onInvited();
    },
  });

  return (
    <>
      <div className="flex flex-wrap items-center gap-3">
        <Button
          type="button"
          size="sm"
          variant="secondary"
          data-testid="admin-families-bulk-invite"
          icon={<Mail className="size-4" aria-hidden="true" />}
          disabled={notInvited.length === 0 || bulkInvite.isPending}
          onClick={() => setBulkOpen(true)}
        >
          Invite all not invited ({notInvitedQuery.isSuccess ? notInvited.length : "—"})
        </Button>
        {bulkNote && (
          <p
            role="status"
            data-testid="admin-families-bulk-invite-result"
            className="text-sm text-rally-muted"
          >
            {bulkNote}
          </p>
        )}
      </div>
      <ConfirmActionDialog
        open={bulkOpen}
        onOpenChange={setBulkOpen}
        overline="Families"
        title="Invite all not invited"
        subject={`${notInvited.length} ${notInvited.length === 1 ? "family" : "families"} with no login yet`}
        consequence={
          <>
            <p>
              Each one is emailed a login invite now. Nothing is charged and no card is asked
              for.
            </p>
            {notInvitedQuery.data && !notInvitedQuery.data.complete ? (
              <p>Only the first {notInvited.length} are included; run it again for the rest.</p>
            ) : null}
          </>
        }
        confirmLabel="Send invites"
        confirmVariant="primary"
        pending={bulkInvite.isPending}
        onConfirm={() => bulkInvite.mutate(notInvited.map((row) => row.parent_id))}
      />
    </>
  );
}

/**
 * #847: one list, two layouts. Exactly one is mounted, so `family-link-<id>`
 * is a single node at every width — see `lib/use-is-phone.ts`.
 */
function FamiliesList({
  rows,
  moneyView,
  state,
  onSort,
}: {
  rows: FamilyResultRow[];
  moneyView: FamilyMoneyView;
  state: FamilyIndexState;
  onSort: (column: FamilyIndexSort) => void;
}) {
  const isPhone = useIsPhone();
  if (isPhone) {
    return (
      <PhoneList aria-label="Families" data-testid="admin-families-phone-list">
        {rows.map((row) =>
          row.kind === "child" ? (
            <ChildPhoneRow key={row.key} family={row.family} child={row.child} />
          ) : (
            <FamilyPhoneRow key={row.key} family={row.family} moneyView={moneyView} />
          ),
        )}
      </PhoneList>
    );
  }
  const moneyVisible = moneyView === "amounts";
  const sortHeader = (column: FamilyIndexSort, label: string, align?: "right") => {
    const sort = ariaSort(state, column, moneyVisible);
    const Icon = sort === "ascending" ? ArrowUp : sort === "descending" ? ArrowDown : ArrowUpDown;
    return (
      <Th ariaSort={sort} align={align}>
        <button
          type="button"
          data-testid={`admin-families-sort-${column}`}
          onClick={() => onSort(column)}
          className="inline-flex items-center gap-1 rounded uppercase hover:text-rally-base focus:outline-none focus:ring-2 focus:ring-rally-cobalt-600"
        >
          {label}
          <Icon className="size-3" aria-hidden="true" />
          <span className="sr-only">
            {sort === "none" ? ", not sorted" : `, sorted ${sort}`}
          </span>
        </button>
      </Th>
    );
  };
  return (
    <div className="overflow-x-auto">
      <table className="w-full text-left text-sm" data-testid="admin-families-table">
        <thead>
          <tr className="border-b border-neutral-200 text-left dark:border-neutral-800">
            {sortHeader("name", "Family")}
            {sortHeader("children", "Children")}
            {sortHeader("stage", "Stage")}
            <Th>Card and login</Th>
            {moneyView === "amounts" ? sortHeader("balance", "Balance", "right") : null}
            {moneyView === "flag" ? <Th align="right">Owes money</Th> : null}
            <Th>Actions</Th>
          </tr>
        </thead>
        <tbody>
          {rows.map((row) =>
            row.kind === "child" ? (
              <ChildTableRow
                key={row.key}
                family={row.family}
                child={row.child}
                moneyView={moneyView}
              />
            ) : (
              <FamilyTableRow key={row.key} family={row.family} moneyView={moneyView} />
            ),
          )}
        </tbody>
      </table>
    </div>
  );
}

function StageChip({ state, asOf }: { state: string | null | undefined; asOf?: string | null }) {
  const label = lifecycleLabel(state, asOf);
  if (!label) return <span className="text-xs text-rally-subtle">—</span>;
  return <Chip variant={lifecycleVariant(state)} label={label} />;
}

function NoAccountChip() {
  return (
    <span
      className="rounded-full bg-status-slate-100 px-2 py-0.5 text-[11px] font-semibold text-status-slate-700"
      title="No login account matches this parent yet, so there is no Billing page."
    >
      No account
    </span>
  );
}

function ChildrenChips({ kids }: { kids: FamilyIndexChild[] }) {
  if (kids.length === 0) return <span className="text-xs text-rally-subtle">No children</span>;
  return (
    <ul className="flex flex-col gap-1">
      {kids.map((child) => (
        <li key={child.student_id} className="flex flex-wrap items-center gap-2">
          <Link
            href={studentHref(child.student_id)}
            className="text-sm text-rally-base hover:underline"
          >
            {child.name}
          </Link>
          <StageChip state={child.lifecycle} asOf={child.lifecycle_as_of} />
        </li>
      ))}
    </ul>
  );
}

function CardLogin({ family }: { family: FamilyIndexRow }) {
  const login = family.registration
    ? loginChip(loginStateFromRegistration(family.registration))
    : null;
  const card =
    family.card_on_file === null ? null : cardChip(family.card_on_file ? "on_file" : "no_card");
  if (!login && !card) return <span className="text-xs text-rally-subtle">—</span>;
  return (
    <div className="flex flex-wrap items-center gap-1">
      {card ? <Chip variant={card.variant} label={card.label} /> : null}
      {login ? <Chip variant={login.variant} label={login.label} /> : null}
    </div>
  );
}

/** The money cell: amounts, the front-desk flag, or unknown (never $0.00). */
function Balance({ family, moneyView }: { family: FamilyIndexRow; moneyView: FamilyMoneyView }) {
  return (
    <FamilyMoneyCell
      display={familyMoneyDisplay(family, moneyView)}
      testId={`admin-families-money-${family.family_id}`}
    />
  );
}

function FamilyName({ family }: { family: FamilyIndexRow }) {
  const href = familyHref(family);
  const name = familyDisplayName(family);
  return href ? (
    <Link
      href={href}
      data-testid={`family-link-${family.family_id}`}
      className="font-medium text-rally-base hover:underline"
    >
      {name}
    </Link>
  ) : (
    <span data-testid={`family-name-${family.family_id}`} className="font-medium text-rally-base">
      {name}
    </span>
  );
}

function FamilyTableRow({
  family,
  moneyView,
}: {
  family: FamilyIndexRow;
  moneyView: FamilyMoneyView;
}) {
  const href = familyHref(family);
  return (
    <tr
      data-testid={`admin-families-row-${family.family_id}`}
      className="border-b border-neutral-100 align-top last:border-0"
    >
      <td className="px-4 py-3">
        <div className="flex flex-wrap items-center gap-2">
          <FamilyName family={family} />
          {!family.has_account ? <NoAccountChip /> : null}
        </div>
        <ContactLinks
          phone={family.phone}
          email={family.email}
          name={familyDisplayName(family)}
          fallback={<span className="text-xs text-rally-subtle">No contact on file</span>}
          className="mt-1 text-xs"
        />
      </td>
      <td className="px-4 py-3">
        <ChildrenChips kids={family.children} />
      </td>
      <td className="px-4 py-3">
        <StageChip state={family.stage} />
      </td>
      <td className="px-4 py-3">
        <CardLogin family={family} />
      </td>
      {moneyView !== "none" ? (
        <td className="px-4 py-3 text-right">
          <Balance family={family} moneyView={moneyView} />
        </td>
      ) : null}
      <td className="px-4 py-3">
        {href ? (
          <Link href={href} className="text-sm font-medium text-rally-cobalt-700 hover:underline">
            Open
          </Link>
        ) : (
          <span className="text-xs text-rally-subtle">No Billing page</span>
        )}
      </td>
    </tr>
  );
}

/** Spec §3.2: a child match is its own result row, linking to the child. */
function ChildTableRow({
  family,
  child,
  moneyView,
}: {
  family: FamilyIndexRow;
  child: FamilyIndexChild;
  moneyView: FamilyMoneyView;
}) {
  const classes = child.classes.map((c) => c.title).filter(Boolean);
  return (
    <tr
      data-testid={`admin-families-child-row-${child.student_id}`}
      className="border-b border-neutral-100 align-top last:border-0"
    >
      <td className="px-4 py-3">
        <Link
          href={studentHref(child.student_id)}
          data-testid={`admin-families-child-link-${child.student_id}`}
          className="font-medium text-rally-base hover:underline"
        >
          {child.name}
        </Link>
        <div className="mt-1 flex flex-wrap items-center gap-1 text-xs text-rally-muted">
          <span>Family:</span>
          <FamilyName family={family} />
          {!family.has_account ? <NoAccountChip /> : null}
        </div>
      </td>
      <td className="px-4 py-3 text-xs text-rally-muted">
        {classes.length > 0 ? classes.join(", ") : "No class"}
      </td>
      <td className="px-4 py-3">
        <StageChip state={child.lifecycle} asOf={child.lifecycle_as_of} />
      </td>
      <td className="px-4 py-3">
        <CardLogin family={family} />
      </td>
      {moneyView !== "none" ? (
        <td className="px-4 py-3 text-right">
          <Balance family={family} moneyView={moneyView} />
        </td>
      ) : null}
      <td className="px-4 py-3">
        <Link
          href={studentHref(child.student_id)}
          className="text-sm font-medium text-rally-cobalt-700 hover:underline"
        >
          Open
        </Link>
      </td>
    </tr>
  );
}

/*
 * #857: the actions trigger is `admin-families-actions-<id>`, deliberately NOT
 * the row testid with `actions-` appended — an id that starts with the row's
 * own `admin-families-row-` prefix is matched by every prefix selector that
 * means to pick rows.
 */
function FamilyPhoneRow({
  family,
  moneyView,
}: {
  family: FamilyIndexRow;
  moneyView: FamilyMoneyView;
}) {
  const href = familyHref(family);
  const name = familyDisplayName(family);
  const classes = familyClasses(family);
  return (
    <PhoneListRow
      data-testid={`admin-families-row-${family.family_id}`}
      title={name}
      href={href ?? undefined}
      titleTestId={href ? `family-link-${family.family_id}` : undefined}
      primary={
        moneyView !== "none" ? (
          <Balance family={family} moneyView={moneyView} />
        ) : (
          <StageChip state={family.stage} />
        )
      }
      actionsLabel={`Actions for ${name}`}
      actionsTestId={`admin-families-actions-${family.family_id}`}
      actions={href ? [{ key: "open", label: "Open family", href }] : []}
      contact={{ email: family.email, phone: family.phone }}
      secondary={
        <>
          <div className="flex flex-wrap items-center gap-2">
            {moneyView !== "none" ? <StageChip state={family.stage} /> : null}
            {!family.has_account ? <NoAccountChip /> : null}
            <CardLogin family={family} />
          </div>
          <ChildrenChips kids={family.children} />
          {classes.length > 0 ? (
            <div className="break-words">{classes.map((c) => c.title).join(", ")}</div>
          ) : null}
        </>
      }
    />
  );
}

function ChildPhoneRow({ family, child }: { family: FamilyIndexRow; child: FamilyIndexChild }) {
  const name = familyDisplayName(family);
  return (
    <PhoneListRow
      data-testid={`admin-families-child-row-${child.student_id}`}
      title={child.name}
      href={studentHref(child.student_id)}
      titleTestId={`admin-families-child-link-${child.student_id}`}
      primary={<StageChip state={child.lifecycle} asOf={child.lifecycle_as_of} />}
      actionsLabel={`Actions for ${child.name}`}
      actionsTestId={`admin-families-child-actions-${child.student_id}`}
      actions={[
        { key: "open-child", label: "Open student", href: studentHref(child.student_id) },
        ...(familyHref(family)
          ? [{ key: "open", label: "Open family", href: familyHref(family)! }]
          : []),
      ]}
      contact={{ email: family.email, phone: family.phone }}
      secondary={
        <div className="flex flex-wrap items-center gap-1">
          <span>Family: {name}</span>
          {!family.has_account ? <NoAccountChip /> : null}
        </div>
      }
    />
  );
}
