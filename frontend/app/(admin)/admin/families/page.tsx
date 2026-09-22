"use client";

/**
 * Admin Families list.
 *
 * Every paying parent with their registration state (card on file, account
 * but no card, not invited), autopay counts and outstanding balance. Actions
 * — invites, charging, autopay — live on the per-family page
 * (`/admin/families/[parentId]`, spec 2026-09-05-family-billing §6).
 */

import { useEffect, useMemo, useState } from "react";
import type { Route } from "next";
import Link from "next/link";
import { useInfiniteQuery, useMutation } from "@tanstack/react-query";
import { Mail } from "lucide-react";

import {
  fetchBillingSetup,
  inviteBillingSetupParent,
  type BillingSetupRegistrationState,
  type BillingSetupRow,
} from "@/lib/api/admin";
import { queryKeys } from "@/lib/query/keys";
import {
  CARD_LABELS,
  LOGIN_LABELS,
  cardChip,
  cardStateFromRegistration,
  loginChip,
  loginStateFromRegistration,
} from "@/lib/people-status";
import { UNKNOWN_TEXT, finiteText } from "@/lib/ui/load-state";
import { visibleFamilyRows, type FamilySort } from "@/lib/admin/family-rows";
import { useIsPhone } from "@/lib/use-is-phone";

import { Button } from "@/components/ds/button";
import { Card } from "@/components/ds/card";
import { ErrorNotice } from "@/components/ds/error-notice";
import { Chip } from "@/components/ds/chip";
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

function formatCents(cents: number): string {
  return new Intl.NumberFormat("en-US", { style: "currency", currency: "USD" }).format(
    cents / 100,
  );
}

function formatDate(iso: string | null): string {
  if (!iso) return "—";
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return "—";
  return d.toLocaleDateString("en-US", { month: "short", day: "numeric" });
}

/**
 * #840: the filter used to say "Chargeable" for the state the chip beside it
 * called "REGISTERED" and the family page called "Card on file". All three now
 * read the one map in `lib/people-status`.
 */
const FILTERS: { value: "all" | BillingSetupRegistrationState; label: string }[] = [
  { value: "all", label: "All" },
  { value: "no_account", label: LOGIN_LABELS.not_invited },
  { value: "account_no_card", label: CARD_LABELS.no_card },
  { value: "card_on_file", label: CARD_LABELS.on_file },
];

const familyHref = (parentId: string) =>
  `/admin/families/${encodeURIComponent(parentId)}` as Route;

export default function FamiliesPage() {
  const [status, setStatus] = useState<"all" | BillingSetupRegistrationState>("all");
  const [q, setQ] = useState("");
  const [debouncedQ, setDebouncedQ] = useState("");
  // #865: both run over the rows already loaded — see `lib/admin/family-rows`
  // for why they are deliberately not a backend filter.
  const [owesOnly, setOwesOnly] = useState(false);
  const [sort, setSort] = useState<FamilySort>("default");

  useEffect(() => {
    const timer = window.setTimeout(() => setDebouncedQ(q.trim()), 300);
    return () => window.clearTimeout(timer);
  }, [q]);

  const params = useMemo(
    () => ({ status, q: debouncedQ || undefined }),
    [status, debouncedQ],
  );
  const {
    data,
    isLoading,
    isError,
    isFetching,
    refetch,
    fetchNextPage,
    hasNextPage,
    isFetchingNextPage,
  } = useInfiniteQuery({
    queryKey: queryKeys.admin.billingSetup(params),
    queryFn: ({ pageParam }) =>
      fetchBillingSetup({ ...params, cursor: pageParam || undefined }),
    initialPageParam: "",
    getNextPageParam: (lastPage) => lastPage.next_cursor ?? undefined,
  });

  const summary = data?.pages[0]?.summary;
  const loadedRows = useMemo(
    () => data?.pages.flatMap((page) => page.rows) ?? [],
    [data],
  );
  const rows = useMemo(
    () => visibleFamilyRows(loadedRows, { owesOnly, sort }),
    [loadedRows, owesOnly, sort],
  );
  const hiddenByOwesFilter = owesOnly && loadedRows.length > 0 && rows.length === 0;

  // #897: the one bulk action this list was missing. `no_account` is the
  // state `LOGIN_LABELS.not_invited` names — a family with no login at all —
  // and it is computed from the rows already loaded, like the owes filter and
  // the sort beside it, so the button can never claim more recipients than
  // this page can see.
  const notInvited = useMemo(
    () => loadedRows.filter((row) => row.registration_state === "no_account"),
    [loadedRows],
  );
  const [bulkOpen, setBulkOpen] = useState(false);
  const [bulkNote, setBulkNote] = useState<string | null>(null);

  const bulkInvite = useMutation({
    // One request per family through the existing per-family endpoint: there
    // is no bulk invite for parents who already exist (`/users/bulk-invite`
    // mints new ones), and inventing one is backend work this issue does not
    // carry.
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
      void refetch();
    },
  });

  return (
    <div className="flex flex-col gap-6" data-testid="admin-families">
      <p className="text-sm text-rally-muted">
        Families · every parent, their card and autopay state; open one for the full picture
      </p>

      {/* #897: accent-top cards with a caption, the shape the Students list
          already uses — these four were the same numbers in a different tile. */}
      <div className="grid grid-cols-2 gap-4 sm:grid-cols-4">
        <Card p={20} accent="#2563eb">
          <Overline>Families</Overline>
          <BigNum>{summary?.families_total ?? "—"}</BigNum>
          <p className="mt-1 text-[11px] text-rally-subtle">Everyone on record</p>
        </Card>
        <Card p={20} accent="#10b981">
          <Overline>{CARD_LABELS.on_file}</Overline>
          <BigNum className="text-rally-cobalt-700">{summary?.families_registered ?? "—"}</BigNum>
          <p className="mt-1 text-[11px] text-rally-subtle">Chargeable today</p>
        </Card>
        <Card p={20} accent="#f59e0b">
          <Overline>{CARD_LABELS.no_card}</Overline>
          <BigNum className="text-rally-volt-700">{summary?.families_no_card ?? "—"}</BigNum>
          <p className="mt-1 text-[11px] text-rally-subtle">Cannot be charged</p>
        </Card>
        <Card p={20} accent="#ef4444">
          <Overline>Outstanding</Overline>
          {/* #837: "$0.00" for a payload that never arrived reads as "nobody
              owes anything"; the sibling tiles already dash out. */}
          <BigNum size={28}>
            {finiteText(summary?.outstanding_total_cents, formatCents, UNKNOWN_TEXT)}
          </BigNum>
          <p className="mt-1 text-[11px] text-rally-subtle">Owed across all families</p>
        </Card>
      </div>

      {bulkNote && (
        <p
          role="status"
          data-testid="admin-families-bulk-invite-result"
          className="text-sm text-rally-muted"
        >
          {bulkNote}
        </p>
      )}

      <ConfirmActionDialog
        open={bulkOpen}
        onOpenChange={setBulkOpen}
        overline="Families"
        title="Invite all not invited"
        subject={`${notInvited.length} ${notInvited.length === 1 ? "family" : "families"} with no login yet`}
        consequence={
          <>
            <p>
              Each one is emailed a login invite now. Nothing is charged and no card is
              asked for.
            </p>
            <p>
              Only the families loaded on this page are included — load more first to
              reach the rest.
            </p>
          </>
        }
        confirmLabel="Send invites"
        confirmVariant="primary"
        pending={bulkInvite.isPending}
        onConfirm={() => bulkInvite.mutate(notInvited.map((row) => row.parent_id))}
      />

      <Card p={0}>
        {/* #897: the Students toolbar's shape, from the design system — this
            filter row used to be its own bordered slate pill group. */}
        <ListToolbar>
          <FilterBar label="Families by registration" testId="admin-families-filters">
            {FILTERS.map((f) => (
              <FilterChip
                key={f.value}
                active={status === f.value}
                label={f.label}
                testId={`admin-families-filter-${f.value}`}
                onClick={() => setStatus(f.value)}
              />
            ))}
            {/* #865: chasing money was the one thing this list could not be
                asked for, though every row already carried the balance. */}
            <FilterChip
              active={owesOnly}
              label="Owes money"
              testId="admin-families-owes-filter"
              onClick={() => setOwesOnly((on) => !on)}
            />
          </FilterBar>

          <div className="flex flex-wrap items-center gap-2 lg:justify-end">
            <Button
              type="button"
              size="sm"
              variant="secondary"
              data-testid="admin-families-bulk-invite"
              icon={<Mail className="size-4" aria-hidden="true" />}
              disabled={notInvited.length === 0 || bulkInvite.isPending}
              onClick={() => setBulkOpen(true)}
            >
              Invite all not invited ({notInvited.length})
            </Button>
            <label htmlFor="admin-families-sort" className="text-sm text-rally-muted">
              Sort
            </label>
            <select
              id="admin-families-sort"
              data-testid="admin-families-sort"
              value={sort}
              onChange={(e) => setSort(e.target.value as FamilySort)}
              className="h-10 rounded-md border border-neutral-200 bg-white px-2 font-body text-sm text-rally-base"
            >
              <option value="default">Default</option>
              <option value="outstanding_desc">Owed, highest first</option>
            </select>
            <ToolbarSearch
              id="admin-families-search"
              label="Search families"
              value={q}
              onChange={setQ}
              placeholder="Search parent name or email"
              busy={isFetching && !isFetchingNextPage}
              busyLabel="Refreshing families"
            />
          </div>
        </ListToolbar>

        {isLoading ? (
          <div className="p-8 text-center text-sm text-slate-500">Loading…</div>
        ) : isError ? (
          <ErrorNotice
            testId="admin-families-error"
            className="m-5"
            message="Could not load Billing Setup. The counts above are unknown, not zero."
            onRetry={() => void refetch()}
            retrying={isFetching}
          />
        ) : rows.length === 0 ? (
          <div className="p-8 text-center text-sm text-slate-500">
            {hiddenByOwesFilter
              ? "No family loaded so far owes anything. Load more families to keep looking."
              : "No families match this filter."}
          </div>
        ) : (
          <FamiliesList rows={rows} />
        )}
        {hasNextPage && (
          <div className="border-t border-rally-line p-4 text-center">
            <Button
              size="sm"
              variant="secondary"
              onClick={() => fetchNextPage()}
              disabled={isFetchingNextPage}
            >
              {isFetchingNextPage ? "Loading…" : "Load more families"}
            </Button>
          </div>
        )}
      </Card>
    </div>
  );
}

/**
 * #847: one list, two layouts. Exactly one is mounted, so `family-link-<id>`
 * is a single node at every width — see `lib/use-is-phone.ts`.
 */
function FamiliesList({ rows }: { rows: BillingSetupRow[] }) {
  const isPhone = useIsPhone();
  if (isPhone) {
    return (
      <PhoneList aria-label="Families" data-testid="admin-families-phone-list">
        {rows.map((row) => (
          <FamilyPhoneRow key={row.parent_id} row={row} />
        ))}
      </PhoneList>
    );
  }
  return (
    <div className="overflow-x-auto">
      <table className="w-full text-left text-sm">
        <thead>
          {/* #897: the mono header the Students and Users tables already
              share — this row was a third, non-mono style. */}
          <tr className="border-b border-neutral-200 text-left dark:border-neutral-800">
            <Th>Parent</Th>
            <Th>Login</Th>
            <Th>Card</Th>
            <Th>Autopay</Th>
            <Th>Outstanding</Th>
            <Th>Invited</Th>
            <Th>Actions</Th>
          </tr>
        </thead>
        <tbody>
          {rows.map((row) => (
            <FamilyTableRow key={row.parent_id} row={row} />
          ))}
        </tbody>
      </table>
    </div>
  );
}

/**
 * The outstanding balance is line 1's primary slot: on a phone it was the
 * fifth column of seven and never on screen, which is the one number that
 * decides whether this family needs chasing today.
 */
/*
 * #857: the actions trigger is `admin-families-actions-<id>`, deliberately NOT
 * the row testid with `actions-` appended — an id that starts with the row's
 * own `admin-families-row-` prefix is matched by every prefix selector that
 * means to pick rows.
 */
function FamilyPhoneRow({ row }: { row: BillingSetupRow }) {
  const login = loginChip(loginStateFromRegistration(row.registration_state));
  const card = cardChip(cardStateFromRegistration(row.registration_state));
  const href = familyHref(row.parent_id);
  const outstanding = row.outstanding_balance_cents;

  return (
    <PhoneListRow
      data-testid={`admin-families-row-${row.parent_id}`}
      title={row.parent_name}
      href={href}
      titleTestId={`family-link-${row.parent_id}`}
      primary={
        <span
          className={`font-mono text-sm font-semibold tabular-nums ${
            outstanding > 0 ? "text-status-red-800" : "text-rally-muted"
          }`}
        >
          {formatCents(outstanding)}
        </span>
      }
      actionsLabel={`Actions for ${row.parent_name}`}
      actionsTestId={`admin-families-actions-${row.parent_id}`}
      actions={[{ key: "open", label: "Open family", href }]}
      // #865: chasing a balance starts with reaching the family.
      contact={{ email: row.parent_email }}
      secondary={
        <>
          <div className="flex flex-wrap items-center gap-2">
            <Chip variant={login.variant} label={login.label} />
            <Chip variant={card.variant} label={card.label} />
          </div>
          <div className="break-words">{row.parent_email ?? "No email on file"}</div>
          {row.card_label && (
            <div>
              {row.card_label} ···· {row.card_last4 ?? "????"}
            </div>
          )}
          <div>
            {row.autopay_active_count > 0 || row.autopay_eligible_count > 0
              ? `${row.autopay_active_count} on autopay · ${row.autopay_eligible_count} eligible to resume`
              : "No autopay"}
            {row.last_invited_at ? ` · invited ${formatDate(row.last_invited_at)}` : ""}
          </div>
          {row.students.length > 0 && (
            <div className="flex flex-wrap gap-1">
              {row.students.map((s) => (
                <span
                  key={s.student_id}
                  className="rounded-full bg-slate-100 px-2 py-0.5 text-[11px] text-slate-600"
                >
                  {s.full_name}
                </span>
              ))}
            </div>
          )}
        </>
      }
    />
  );
}

function FamilyTableRow({ row }: { row: BillingSetupRow }) {
  const login = loginChip(loginStateFromRegistration(row.registration_state));
  const card = cardChip(cardStateFromRegistration(row.registration_state));
  const href = familyHref(row.parent_id);

  return (
    <tr className="border-b border-slate-100 last:border-0">
      <td className="px-4 py-3">
        <Link
          href={href}
          data-testid={`family-link-${row.parent_id}`}
          className="font-medium text-slate-900 hover:underline"
        >
          {row.parent_name}
        </Link>
        <div className="text-xs text-slate-500">{row.parent_email ?? "—"}</div>
        <div className="mt-1 flex flex-wrap gap-1">
          {row.students.map((s) => (
            <span
              key={s.student_id}
              className="rounded-full bg-slate-100 px-2 py-0.5 text-[11px] text-slate-600"
            >
              {s.full_name}
            </span>
          ))}
        </div>
      </td>
      <td className="px-4 py-3">
        <Chip variant={login.variant} label={login.label} />
      </td>
      <td className="px-4 py-3 text-slate-700">
        <Chip variant={card.variant} label={card.label} />
        {row.card_label && (
          <div className="mt-1 text-xs text-slate-500">
            {row.card_label} ···· {row.card_last4 ?? "????"}
          </div>
        )}
      </td>
      <td className="px-4 py-3 text-slate-700">
        {/* #840: "resumable" was the autopay-eligibility predicate's own name
            leaking into the page; say what an admin would say. */}
        {row.autopay_active_count > 0 || row.autopay_eligible_count > 0
          ? `${row.autopay_active_count} on autopay · ${row.autopay_eligible_count} eligible to resume`
          : "—"}
      </td>
      <td className="px-4 py-3 text-slate-700">{formatCents(row.outstanding_balance_cents)}</td>
      <td className="px-4 py-3 text-slate-500">
        {row.last_invited_at ? formatDate(row.last_invited_at) : "—"}
      </td>
      <td className="px-4 py-3">
        <Link href={href} className="text-sm font-medium text-rally-cobalt-700 hover:underline">
          Open
        </Link>
      </td>
    </tr>
  );
}
