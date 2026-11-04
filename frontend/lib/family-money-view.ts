/**
 * Claims-aware family money display (L2b, #553).
 *
 * Owner decision 2026-09-22: owner, admin and billing see family money
 * amounts; front desk sees an "Owes money" flag with no amount. The SERVER
 * redacts: a front-desk payload has `money: null` and only `owes_money`
 * (backend/v2/interfaces/admin/family_index_views.py). This module only
 * decides how to render what came back, plus the owner's "Viewing as"
 * preview, which can narrow what the owner sees and never widen it.
 */
import type { FamilyIndexRow, FamilyMoneyView } from "@/lib/api/admin-families";

/** Who the owner is previewing the page as. `self` is no preview. */
export type ViewingAs = "self" | "billing" | "front_desk";

export const VIEWING_AS_OPTIONS: ReadonlyArray<{ id: ViewingAs; label: string }> = [
  { id: "self", label: "Owner (you)" },
  { id: "billing", label: "Billing" },
  { id: "front_desk", label: "Front desk" },
];

export function isViewingAs(value: unknown): value is ViewingAs {
  return value === "self" || value === "billing" || value === "front_desk";
}

/** The server's money view; responses before L2b only carry `money_visible`. */
export function serverMoneyView(payload: {
  money_view?: FamilyMoneyView | null;
  money_visible: boolean;
}): FamilyMoneyView {
  return payload.money_view ?? (payload.money_visible ? "amounts" : "none");
}

/**
 * The view to render: the server's view, narrowed by the owner's preview.
 * Billing sees amounts like the owner; front desk sees the flag. A preview
 * never widens: `flag` or `none` from the server stays as it is.
 */
export function effectiveMoneyView(server: FamilyMoneyView, viewingAs: ViewingAs): FamilyMoneyView {
  if (server !== "amounts") return server;
  return viewingAs === "front_desk" ? "flag" : "amounts";
}

export type FamilyMoneyDisplay =
  | {
      kind: "amount";
      balanceCents: number;
      overdueCents: number;
      overdueCount: number;
      openCount: number;
    }
  | { kind: "owes" }
  | { kind: "clear" }
  | { kind: "unknown" }
  | { kind: "hidden" };

/**
 * What one family's money cell shows. `unknown` (money could not be read)
 * is never rendered as $0.00 or "Paid up".
 */
export function familyMoneyDisplay(
  row: Pick<FamilyIndexRow, "money" | "owes_money">,
  view: FamilyMoneyView,
): FamilyMoneyDisplay {
  if (view === "none") return { kind: "hidden" };
  if (view === "amounts") {
    const money = row.money;
    if (!money) return { kind: "unknown" };
    return {
      kind: "amount",
      balanceCents: money.balance_cents,
      overdueCents: money.overdue_cents,
      overdueCount: money.overdue_invoice_count,
      openCount: money.open_invoice_count,
    };
  }
  // flag: the server's yes/no is authoritative. The balance fallback exists
  // only for an owner previewing front desk against a server that predates
  // `owes_money` (field absent, i.e. undefined). A real front-desk response
  // always carries `money: null`, so it never reaches the fallback with an
  // amount, and an explicit `owes_money: null` means "unknown" and stays
  // unknown rather than being re-derived from an amount sent alongside it.
  // Remove the fallback once every deployed backend sends `money_view`.
  let owes: boolean | null;
  if (row.owes_money !== undefined) owes = row.owes_money;
  else owes = row.money ? row.money.balance_cents > 0 : null;
  if (owes === null) return { kind: "unknown" };
  return owes ? { kind: "owes" } : { kind: "clear" };
}
