"use client";

import { Card, Chip, Overline } from "@/components/ds";
import type { FamilyIndexRow, FamilyParent } from "@/lib/api/admin-families";
import { lifecycleLabel, lifecycleVariant } from "@/lib/format/lifecycle-copy";

import {
  SECOND_PARENT_NOTE,
  SECOND_PARENT_SWITCHES,
  primaryContactRows,
  type OverviewChild,
} from "./family-record";

/**
 * Details (People CRM spec §4), read-only. It shows the contact data that
 * already exists: the parent's profile (name, email, phone) and the children.
 * Editable family details and second-parent contacts are Phase 4
 * (`family_details`, `family_contacts`), so the second-parent switches are
 * shown disabled with a note rather than saving nowhere.
 */
export function DetailsTab({
  family,
  parent,
  kids,
}: {
  family: FamilyIndexRow | null;
  parent: FamilyParent | null;
  kids: OverviewChild[];
}) {
  return (
    <div className="space-y-4" data-testid="family-details">
      <Card p={20}>
        <Overline>Primary parent</Overline>
        <dl className="mt-2 grid gap-2 sm:grid-cols-[8rem_1fr]">
          {primaryContactRows(family, parent).map((row) => (
            <div key={row.label} className="contents">
              <dt className="text-sm text-rally-muted">{row.label}</dt>
              <dd className="text-sm text-rally-ink" data-testid={row.testId}>
                {row.value}
              </dd>
            </div>
          ))}
        </dl>
        <p className="mt-3 text-xs text-rally-muted">
          Name, email and phone come from the parent&apos;s login account.
        </p>
      </Card>

      <Card p={20} data-testid="family-details-second-parent">
        <Overline>Second parent or guardian</Overline>
        <p
          id="second-parent-note"
          className="mt-2 text-sm text-rally-muted"
          data-testid="second-parent-note"
        >
          {SECOND_PARENT_NOTE}
        </p>
        <div className="mt-3 space-y-2">
          {SECOND_PARENT_SWITCHES.map((sw) => (
            <label key={sw.id} className="flex min-h-11 items-center gap-3 text-sm text-rally-muted">
              <input
                type="checkbox"
                role="switch"
                aria-checked={sw.checked}
                checked={sw.checked}
                disabled={sw.disabled}
                readOnly
                aria-describedby="second-parent-note"
                data-testid={`second-parent-${sw.id}`}
                className="size-5 accent-rally-cobalt-600"
              />
              {sw.label}
            </label>
          ))}
        </div>
      </Card>

      <Card p={20}>
        <Overline>Children</Overline>
        {kids.length === 0 ? (
          <p className="mt-2 text-sm text-rally-muted">No children on this family yet.</p>
        ) : (
          <ul className="mt-2 space-y-2" data-testid="family-details-children">
            {kids.map((kid) => (
              <li key={kid.studentId} className="flex flex-wrap items-center gap-2 text-sm">
                <span className="text-rally-ink">{kid.name}</span>
                {kid.lifecycle && (
                  <Chip
                    variant={lifecycleVariant(kid.lifecycle)}
                    label={lifecycleLabel(kid.lifecycle, kid.lifecycleAsOf)}
                  />
                )}
              </li>
            ))}
          </ul>
        )}
      </Card>
    </div>
  );
}
