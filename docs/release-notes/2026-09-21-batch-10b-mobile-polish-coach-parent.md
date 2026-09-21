# batch-10b: mobile polish for coach header, calendar, and parent screens

PR: #0

## What changed
- Fixes #866 — Coach header no longer wraps at 400px: Calendar/Messages/Needs-review moved from the sticky header into the bottom nav, preserving existing data-testids.
- Fixes #866 — PersonaCalendarView's FullCalendar toolbar now wraps instead of crowding at narrow widths, and its buttons/today-highlight use the Rally cobalt token instead of stock blue (scoped to a CSS module so AdminCalendarView is untouched).
- Fixes #866 — Swapped neutral Tailwind greys for rally-line/white tokens in the calendar module, matching the rest of the Rally design system.
- Fixes #866 — Waiver "Accept" and every onboarding Next/Back/Retry/Accept button now use the shared DS Button (cobalt primary / secondary) instead of the "volt" variant or the dead, undefined `.primary`/`.secondary` classes.
- Fixes #866 — Added a "Secure checkout via Stripe" reassurance line under the parent balance and per-invoice Pay buttons.
- Fixes #866 — Absence-notice and makeup-request rows now show the child's name; MakeupsPanel gained its own `listParentChildren` fetch, mirroring AbsencesPanel.
- Payments' existing button hierarchy was reviewed and confirmed already compliant, so left untouched.

## Deploy notes
No migrations. Frontend-only change (coach layout, parent onboarding/payments/requests/waivers pages, and PersonaCalendarView). No manual env var or manual step needed before merge.

## Risk / rollback
Low risk: purely visual/UI changes to the coach header, calendar toolbar styling, DS Button usage, and two parent panels' data fetching (read-only `listParentChildren` calls). No changes to bulk-eligibility, bulk-mark-undo, the offline queue, or checkout logic. If this regresses, revert this PR's merge commit.
