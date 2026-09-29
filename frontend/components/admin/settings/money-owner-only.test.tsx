import { readFileSync } from "node:fs";
import path from "node:path";
import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it } from "vitest";

import { OwnerOnlyFieldNote } from "@/components/admin/owner-context";
import { cancellationTermsSummary } from "@/lib/self-service-policy-form";
import type { SessionTypeView } from "@/lib/api/v2/session-types";

import { CurrencySelect, TimezoneSelect } from "./academy-panel";
import { SessionTypesTable } from "./session-types-panel";

// Settings overhaul Phase 1 PR 5: money is owner-only. An admin without the
// owner scope sees prices, fees and the timezone disabled with an "Owner
// only" hint; an owner sees no change.

const noop = () => undefined;

function source(relative: string): string {
  return readFileSync(path.resolve(__dirname, "../../..", relative), "utf8");
}

describe("OwnerOnlyFieldNote", () => {
  it("says who can change the field", () => {
    const html = renderToStaticMarkup(<OwnerOnlyFieldNote id="note" />);
    expect(html).toContain("Owner only");
    expect(html).toContain("Only the academy owner can change this.");
    expect(html).toContain('id="note"');
  });
});

describe("Academy timezone and currency", () => {
  it("are disabled with the owner-only note for an admin", () => {
    const tz = renderToStaticMarkup(
      <TimezoneSelect value="America/Chicago" onChange={noop} locked />,
    );
    const currency = renderToStaticMarkup(<CurrencySelect value="USD" onChange={noop} locked />);
    for (const html of [tz, currency]) {
      expect(html).toMatch(/<select[^>]*disabled=""/);
      expect(html).toContain("owner-only-field-note");
    }
  });

  it("stay editable for the owner", () => {
    const tz = renderToStaticMarkup(<TimezoneSelect value="America/Chicago" onChange={noop} />);
    const currency = renderToStaticMarkup(<CurrencySelect value="USD" onChange={noop} />);
    for (const html of [tz, currency]) {
      expect(html).not.toMatch(/<select[^>]*disabled=""/);
      expect(html).not.toContain("owner-only-field-note");
    }
  });
});

describe("Session types (price list)", () => {
  const row: SessionTypeView = {
    session_type_id: "type-1",
    name: "Elite",
    description: null,
    price_cents: 20_000,
    billing_period: "monthly",
    overage_rate_cents: null,
    is_active: true,
    created_at: "2026-09-01T00:00:00Z",
    updated_at: "2026-09-01T00:00:00Z",
  };
  const props = {
    rows: [row],
    onEdit: noop,
    onArchive: noop,
    onReactivate: noop,
    reactivatingId: null,
    failedReactivateId: null,
  };

  it("shows prices read-only with an Owner only hint for an admin", () => {
    const html = renderToStaticMarkup(<SessionTypesTable {...props} canEdit={false} />);
    expect(html).toContain("$200.00");
    expect(html).toContain("owner-only-hint");
    expect(html).not.toContain(">Edit<");
    expect(html).not.toContain(">Archive<");
  });

  it("keeps Edit and Archive for the owner", () => {
    const html = renderToStaticMarkup(<SessionTypesTable {...props} canEdit />);
    expect(html).toContain(">Edit<");
    expect(html).toContain(">Archive<");
    expect(html).not.toContain("owner-only-hint");
  });
});

describe("Class monthly fee", () => {
  it("is disabled for a non-owner in the list page edit and create dialogs", () => {
    const page = source("app/(admin)/admin/sessions/page.tsx");
    expect(page.match(/disabled=\{!isOwner\}/g)?.length).toBe(2);
    expect(page).toContain("<OwnerOnlyFieldNote");
    // A non-owner never sends a fee on create: the BFF would 403 it.
    expect(page).toMatch(/isOwner \? form : \{ \.\.\.form, amount_cents: null \}/);
  });

  it("is disabled for a non-owner in the session detail edit dialog", () => {
    const detail = source("app/(admin)/admin/sessions/[id]/SessionEditing.tsx");
    expect(detail).toMatch(/useIsOwner\(\)/);
    expect(detail).toMatch(/disabled=\{!isOwner\}/);
    expect(detail).toContain("<OwnerOnlyFieldNote");
  });
});

describe("Self-service cancellation terms", () => {
  it("are summarised and pointed at Billing rules, not edited", () => {
    expect(
      cancellationTermsSummary({ cancellation_minimum_notice_days: 7, cancellation_fee_cents: 2500 }),
    ).toBe("7 days notice, $25.00 fee when notice is short. Set in Billing rules.");
    expect(
      cancellationTermsSummary({ cancellation_minimum_notice_days: 1, cancellation_fee_cents: 0 }),
    ).toBe("1 day notice, no fee. Set in Billing rules.");
    expect(cancellationTermsSummary(null)).toBe("Set in Billing rules.");
  });
});
