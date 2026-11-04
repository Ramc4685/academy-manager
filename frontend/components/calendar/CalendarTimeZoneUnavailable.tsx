import Link from "next/link";

import { Card } from "@/components/ds/card";

/**
 * #1043: the calendar's safe state when the academy timezone is missing or
 * not a real IANA zone. Drawing the grid anyway would put classes on the
 * viewer's browser clock — a guessed time, and near midnight a wrong day —
 * so the grid is withheld and the viewer is pointed at the list screen,
 * which labels every time explicitly.
 */
export function CalendarTimeZoneUnavailable({
  listHref,
  listLabel,
}: {
  listHref: "/coach/sessions" | "/parent/children";
  listLabel: string;
}) {
  return (
    <Card p={16}>
      <div role="status" data-testid="calendar-timezone-unavailable" className="space-y-2">
        <p className="text-sm font-semibold text-rally-ink">Calendar times unavailable</p>
        <p className="text-sm text-rally-muted">
          The academy&apos;s timezone isn&apos;t set, so class times can&apos;t be placed on the
          calendar reliably. See{" "}
          <Link href={listHref} className="font-semibold text-rally-cobalt underline">
            {listLabel}
          </Link>{" "}
          for your classes.
        </p>
      </div>
    </Card>
  );
}
