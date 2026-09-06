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
import { useInfiniteQuery } from "@tanstack/react-query";

import {
  fetchBillingSetup,
  type BillingSetupRegistrationState,
  type BillingSetupRow,
} from "@/lib/api/admin";
import { queryKeys } from "@/lib/query/keys";

import { Button } from "@/components/ds/button";
import { Card } from "@/components/ds/card";
import { Chip, type ChipVariant } from "@/components/ds/chip";
import { BigNum, Overline } from "@/components/ds/typography";

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

function stateChip(state: BillingSetupRegistrationState): { variant: ChipVariant; label: string } {
  if (state === "card_on_file") return { variant: "paid", label: "REGISTERED" };
  if (state === "account_no_card") return { variant: "pending", label: "NO CARD" };
  return { variant: "nocharge", label: "NOT INVITED" };
}

const FILTERS: { value: "all" | BillingSetupRegistrationState; label: string }[] = [
  { value: "all", label: "All" },
  { value: "no_account", label: "Not invited" },
  { value: "account_no_card", label: "No card" },
  { value: "card_on_file", label: "Chargeable" },
];

const familyHref = (parentId: string) =>
  `/admin/families/${encodeURIComponent(parentId)}` as Route;

export default function FamiliesPage() {
  const [status, setStatus] = useState<"all" | BillingSetupRegistrationState>("all");
  const [q, setQ] = useState("");
  const [debouncedQ, setDebouncedQ] = useState("");

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
  const rows = data?.pages.flatMap((page) => page.rows) ?? [];

  return (
    <div className="flex flex-col gap-6" data-testid="admin-families">
      <p className="text-sm text-rally-muted">
        Families · every parent, their card and autopay state; open one for the full picture
      </p>

      <div className="grid grid-cols-1 gap-4 sm:grid-cols-4">
        <Card p={20}>
          <Overline>Families</Overline>
          <BigNum>{summary?.families_total ?? "—"}</BigNum>
        </Card>
        <Card p={20}>
          <Overline>Registered</Overline>
          <BigNum className="text-rally-cobalt-700">{summary?.families_registered ?? "—"}</BigNum>
        </Card>
        <Card p={20}>
          <Overline>Missing a card</Overline>
          <BigNum className="text-rally-volt-700">{summary?.families_no_card ?? "—"}</BigNum>
        </Card>
        <Card p={20}>
          <Overline>Outstanding</Overline>
          <BigNum size={28}>{formatCents(summary?.outstanding_total_cents ?? 0)}</BigNum>
        </Card>
      </div>

      <div className="flex flex-wrap items-center gap-3">
        <div className="flex gap-1 rounded-md border border-slate-200 bg-white p-1">
          {FILTERS.map((f) => (
            <button
              key={f.value}
              onClick={() => setStatus(f.value)}
              className={`rounded px-3 py-1.5 text-sm font-medium ${
                status === f.value ? "bg-slate-900 text-white" : "text-slate-600 hover:bg-slate-100"
              }`}
            >
              {f.label}
            </button>
          ))}
        </div>
        <input
          value={q}
          onChange={(e) => setQ(e.target.value)}
          placeholder="Search parent name or email…"
          className="w-64 rounded-md border border-slate-200 px-3 py-1.5 text-sm"
        />
      </div>

      <Card p={0}>
        {isLoading ? (
          <div className="p-8 text-center text-sm text-slate-500">Loading…</div>
        ) : isError ? (
          <div className="p-8 text-center text-sm text-red-600">Failed to load Billing Setup.</div>
        ) : rows.length === 0 ? (
          <div className="p-8 text-center text-sm text-slate-500">No families match this filter.</div>
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full text-left text-sm">
              <thead>
                <tr className="border-b border-slate-200 text-xs uppercase text-slate-500">
                  <th className="px-4 py-3">Parent</th>
                  <th className="px-4 py-3">Status</th>
                  <th className="px-4 py-3">Card</th>
                  <th className="px-4 py-3">Autopay</th>
                  <th className="px-4 py-3">Outstanding</th>
                  <th className="px-4 py-3">Invited</th>
                  <th className="px-4 py-3">Actions</th>
                </tr>
              </thead>
              <tbody>
                {rows.map((row) => (
                  <FamilyTableRow key={row.parent_id} row={row} />
                ))}
              </tbody>
            </table>
          </div>
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

function FamilyTableRow({ row }: { row: BillingSetupRow }) {
  const chip = stateChip(row.registration_state);
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
        <Chip variant={chip.variant} label={chip.label} />
      </td>
      <td className="px-4 py-3 text-slate-700">
        {row.card_label ? `${row.card_label} ···· ${row.card_last4 ?? "????"}` : "—"}
      </td>
      <td className="px-4 py-3 text-slate-700">
        {row.autopay_active_count > 0 || row.autopay_eligible_count > 0
          ? `${row.autopay_active_count} active · ${row.autopay_eligible_count} resumable`
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
