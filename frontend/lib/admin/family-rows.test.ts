import { describe, expect, it } from "vitest";

import type { BillingSetupRow } from "@/lib/api/admin";
import { visibleFamilyRows } from "./family-rows";

/**
 * Issue #865: the Families list carried `outstanding_balance_cents` on every
 * row and offered no way to see only the families who owe, or to put the
 * biggest debt first. Chasing money meant reading all seven columns down a
 * page sorted by nothing in particular.
 */

function row(parentId: string, outstanding: number): BillingSetupRow {
  return {
    parent_id: parentId,
    parent_name: parentId,
    parent_email: `${parentId}@example.com`,
    students: [],
    registration_state: "card_on_file",
    card_label: null,
    card_last4: null,
    autopay_active_count: 0,
    autopay_eligible_count: 0,
    outstanding_balance_cents: outstanding,
    charge_invoice_id: null,
    charge_amount_cents: 0,
    charge_autopay_eligible: false,
    last_invited_at: null,
  };
}

const ROWS = [row("ada", 0), row("bo", 12_500), row("cy", 400), row("di", 0)];

describe("visibleFamilyRows (#865)", () => {
  it("keeps the server's order when nothing is asked of it", () => {
    expect(visibleFamilyRows(ROWS).map((r) => r.parent_id)).toEqual(["ada", "bo", "cy", "di"]);
  });

  it("owesOnly drops every family with a zero balance", () => {
    expect(visibleFamilyRows(ROWS, { owesOnly: true }).map((r) => r.parent_id)).toEqual([
      "bo",
      "cy",
    ]);
  });

  it("a credit balance is not money owed", () => {
    const rows = [row("ada", -5_000), row("bo", 1)];
    expect(visibleFamilyRows(rows, { owesOnly: true }).map((r) => r.parent_id)).toEqual(["bo"]);
  });

  it("sorts biggest outstanding first", () => {
    expect(visibleFamilyRows(ROWS, { sort: "outstanding_desc" }).map((r) => r.parent_id)).toEqual([
      "bo",
      "cy",
      "ada",
      "di",
    ]);
  });

  it("ties keep the order the server sent, so the list does not shuffle on refetch", () => {
    const rows = [row("ada", 100), row("bo", 100), row("cy", 100)];
    expect(visibleFamilyRows(rows, { sort: "outstanding_desc" }).map((r) => r.parent_id)).toEqual([
      "ada",
      "bo",
      "cy",
    ]);
  });

  it("filters and sorts together", () => {
    expect(
      visibleFamilyRows(ROWS, { owesOnly: true, sort: "outstanding_desc" }).map((r) => r.parent_id),
    ).toEqual(["bo", "cy"]);
  });

  it("never mutates the array it was handed", () => {
    const rows = [row("ada", 1), row("bo", 9)];
    visibleFamilyRows(rows, { sort: "outstanding_desc" });
    expect(rows.map((r) => r.parent_id)).toEqual(["ada", "bo"]);
  });
});
