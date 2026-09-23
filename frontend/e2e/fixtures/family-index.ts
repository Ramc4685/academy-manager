import type { Page, Request } from "@playwright/test";

import { fulfillJson } from "./saas-stubs";

/**
 * Stubs for the People CRM family index (`GET /api/v2/admin/families` and
 * `/api/v2/admin/families/summary`, engineering-spec §3.2). Shapes mirror
 * `backend/v2/interfaces/admin/family_index_views.py`. Names are fake.
 */

export interface FamilyIndexRowFixture {
  family_id: string;
  parent_name: string | null;
  email: string | null;
  phone: string | null;
  has_account: boolean;
  stage: string;
  children: {
    student_id: string;
    name: string;
    lifecycle: string;
    lifecycle_as_of: string | null;
    classes: { session_id: string; title: string }[];
    matched: boolean;
  }[];
  card_on_file: boolean | null;
  registration: "registered" | "invited" | "not_invited" | null;
  money: {
    balance_cents: number;
    open_invoice_count: number;
    overdue_invoice_count: number;
    overdue_cents: number;
    oldest_overdue_due_on: string | null;
    last_failed_payment_at: string | null;
  } | null;
  matched_parent: boolean;
}

export function familyIndexRow(
  overrides: Partial<FamilyIndexRowFixture> = {},
): FamilyIndexRowFixture {
  return {
    family_id: "parent-1",
    parent_name: "Test Parent One",
    email: "parent.one@example.test",
    phone: null,
    has_account: true,
    stage: "active",
    children: [],
    card_on_file: true,
    registration: "registered",
    money: null,
    matched_parent: false,
    ...overrides,
  };
}

export const FAMILY_PRESETS = [
  { id: "active", label: "Active", params: { scope: "active" }, money: false },
  { id: "leaving", label: "Leaving", params: { scope: "leaving" }, money: false },
  { id: "left", label: "Left", params: { scope: "left" }, money: false },
  { id: "overdue", label: "Overdue", params: { overdue: "true" }, money: true },
  { id: "no_card", label: "No card", params: { card_on_file: "false" }, money: false },
];

export interface FamilyIndexStubOptions {
  /** Rows for a given request; defaults to every row, unfiltered. */
  families?: FamilyIndexRowFixture[] | ((url: URL) => FamilyIndexRowFixture[]);
  moneyVisible?: boolean;
  tiles?: { active: number; leaving: number; left: number };
  /** The Overdue / No card chip counts; `overdue` is dropped when money is hidden. */
  presetCounts?: { overdue?: number; no_card?: number };
  warnings?: string[];
  onList?: (request: Request) => void;
}

export async function stubFamilyIndex(page: Page, opts: FamilyIndexStubOptions = {}) {
  const moneyVisible = opts.moneyVisible ?? true;
  const rowsFor = (url: URL) =>
    typeof opts.families === "function" ? opts.families(url) : (opts.families ?? []);
  await page.route(/\/api\/v2\/admin\/families\/summary(?:\?.*)?$/, (route) => {
    const tiles = opts.tiles ?? { active: 0, leaving: 0, left: 0 };
    return fulfillJson(route, {
      generated_at: "2026-09-23T15:00:00Z",
      total_families: tiles.active + tiles.leaving + tiles.left,
      tiles,
      counts_by_stage: {},
      presets: FAMILY_PRESETS.filter((p) => moneyVisible || !p.money),
      preset_counts: Object.fromEntries(
        Object.entries(opts.presetCounts ?? {}).filter(([id]) => moneyVisible || id !== "overdue"),
      ),
      warnings: opts.warnings ?? [],
    });
  });
  await page.route(/\/api\/v2\/admin\/families(?:\?.*)?$/, (route) => {
    const req = route.request();
    if (req.method() !== "GET") return route.fallback();
    opts.onList?.(req);
    const url = new URL(req.url());
    const rows = rowsFor(url).map((row) => (moneyVisible ? row : { ...row, money: null }));
    return fulfillJson(route, {
      generated_at: "2026-09-23T15:00:00Z",
      families: rows,
      total: rows.length,
      page: Number(url.searchParams.get("page") ?? "1"),
      page_size: Number(url.searchParams.get("page_size") ?? "50"),
      money_visible: moneyVisible,
      warnings: opts.warnings ?? [],
    });
  });
}

/** The bulk invite reads Billing Setup; an empty page keeps it quiet. */
export async function stubEmptyBillingSetup(page: Page) {
  await page.route("**/api/v2/admin/billing/setup*", (route) =>
    fulfillJson(route, {
      rows: [],
      summary: {
        families_total: 0,
        families_registered: 0,
        families_no_card: 0,
        outstanding_total_cents: 0,
      },
      next_cursor: null,
    }),
  );
}
