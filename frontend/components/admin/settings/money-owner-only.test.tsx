import { readFileSync } from "node:fs";
import path from "node:path";
import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it } from "vitest";

import { OwnerOnlyFieldNote } from "@/components/admin/owner-context";
import { cancellationTermsSummary } from "@/lib/self-service-policy-form";
import type { SessionTypeView } from "@/lib/api/v2/session-types";

import { TimezoneSelect } from "./academy-panel";
import { PlansTable } from "@/components/admin/pricing/plans-card";

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

describe("Academy timezone (currency is a read-only USD field)", () => {
  it("are disabled with the owner-only note for an admin", () => {
    const tz = renderToStaticMarkup(
      <TimezoneSelect value="America/Chicago" onChange={noop} locked />,
    );
    for (const html of [tz]) {
      expect(html).toMatch(/<select[^>]*disabled=""/);
      expect(html).toContain("owner-only-field-note");
    }
  });

  it("stay editable for the owner", () => {
    const tz = renderToStaticMarkup(<TimezoneSelect value="America/Chicago" onChange={noop} />);
    for (const html of [tz]) {
      expect(html).not.toMatch(/<select[^>]*disabled=""/);
      expect(html).not.toContain("owner-only-field-note");
    }
  });
});

describe("Plans (price list, Pricing page)", () => {
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
    const html = renderToStaticMarkup(<PlansTable {...props} canEdit={false} />);
    expect(html).toContain("$200.00");
    expect(html).toContain("owner-only-hint");
    expect(html).not.toContain(">Edit<");
    expect(html).not.toContain(">Archive<");
  });

  it("keeps Edit and Archive for the owner", () => {
    const html = renderToStaticMarkup(<PlansTable {...props} canEdit />);
    expect(html).toContain(">Edit<");
    expect(html).toContain(">Archive<");
    expect(html).not.toContain("owner-only-hint");
  });
});

describe("Class monthly fee", () => {
  // Class-page PR A: Create, list Edit and class-page Edit share one form;
  // its rendered owner/non-owner states are pinned in
  // components/admin/sessions/class-form.test.tsx.
  it("every class dialog is the shared, owner-gated class form", () => {
    const page = source("app/(admin)/admin/sessions/page.tsx");
    expect(page).toContain("<CreateClassDialog");
    expect(page).toContain("<EditClassDialog");
    const detail = source("app/(admin)/admin/sessions/[id]/SessionEditing.tsx");
    expect(detail).toMatch(/SessionEditDialog = EditClassDialog/);
  });

  it("is read-only for a non-owner, and a non-owner never sends a fee", () => {
    const form = source("components/admin/sessions/class-form.tsx");
    expect(form).toMatch(/useIsOwner\(\)/);
    expect(form).toContain("<OwnerOnlyFieldNote");
    // Create: the BFF would 403 any fee from a non-owner.
    expect(form).toMatch(/const fee = isOwner\s*\?[\s\S]*?: null;/);
  });
});

describe("Self-service cancellation terms", () => {
  it("are summarised and pointed at Billing rules, not edited", () => {
    expect(
      cancellationTermsSummary({
        cancellation_minimum_notice_days: 7,
        cancellation_fee_cents: 2500,
        cancellation_effective_timing: "end_of_period",
      }),
    ).toBe("7 days notice, $25.00 fee when notice is short, takes effect at period end. Set in Billing rules.");
    expect(
      cancellationTermsSummary({
        cancellation_minimum_notice_days: 1,
        cancellation_fee_cents: 0,
        cancellation_effective_timing: "immediate",
      }),
    ).toBe("1 day notice, no fee, takes effect immediately. Set in Billing rules.");
    expect(cancellationTermsSummary(null)).toBe("Set in Billing rules.");
  });
});
