# fix-uim8-tuition-discounts

PR: #359

## What changed
Adds a Tuition discounts section to the admin Dues page
(`app/(admin)/admin/dues/page.tsx`), wired to the previously dark
`GET /admin/finance/tuition-discounts?period=YYYY-MM` route
(`backend/v2/interfaces/admin/billing_routes.py:717`, DTO
`AdminTuitionDiscountSummaryResponse`). Admins can now see gross tuition,
total discounts, and net tuition for a selected month, plus a per-category
discount breakdown with percent-of-gross, instead of discounting being an
invisible cost.

Note on placement: the UIM8 plan (and the task that dispatched this PR)
assumed UIC3 (session economics + dues merged into a tabbed Reports page)
had already landed. It has not — `docs/audit/TRACKER.md` still lists UIC3 as
`TODO` and `app/(admin)/admin/reports/page.tsx` has no tabs. Per the UIM8
plan's own fallback ("If UIC3 has not landed yet, build it on the existing
dues page ... do not create a new standalone page"), this section was added
to the existing `/admin/dues` page instead. When UIC3 ships, this section
should move into the merged Reports surface.

New API client function `getTuitionDiscountSummary(period)` and types in
`lib/api/admin.ts`; new query key `queryKeys.admin.tuitionDiscounts(period)`
in `lib/query/keys.ts`. The selected month is kept in the `discounts_period`
URL search param so the view is linkable, following the pattern already used
on `/admin/payouts`.

## Deploy notes
None — frontend-only, no schema/migration/env changes. The backend route and
query were already deployed and dark; this only adds a caller.

## Risk / rollback
Low. Purely additive UI section; no existing dues-page behavior changed.
Rollback = revert this PR. Coordination risk: if UIC3 lands first in a
future PR, that PR should move this section rather than duplicate it.
