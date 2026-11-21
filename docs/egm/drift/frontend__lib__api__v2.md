## frontend/lib/api/v2/README.md

- [stale-not-built] README:25 says `students.ts` calls "admin student progress and placement endpoints". `students.ts` has no progress or placement calls. It covers student detail, invoices, enrollment transfer, tuition discount and fee, and now not-billed.
- [stale-not-built] README:24 says `sessions.ts` calls "admin session and occurrence endpoints". It only calls `/admin/session-occurrences/*` coach-attendance, coach and replacement (`sessions.ts:28,37,46`). There are no session endpoints.
- [contract] README:27-28 says `GET` returns active types only. `listSessionTypes` accepts `includeArchived` and sends `?include_archived=true` (`session-types.ts:54-60`), so archived types can be listed.
- [contract] README:29-31 says `memberships.ts` derives a single active academy from `/me` because `/me/memberships` is not exposed. The code calls `GET /me/memberships` directly (`memberships.ts:45`). The only fallback left is a placeholder academy name (`deriveAcademyLabel`).
- [undocumented] `students.ts:244` `setEnrollmentBilling` (`PUT /admin/enrollments/{id}/billing`, owner only), with `SetEnrollmentBillingRequest`, `EnrollmentBillingView` and `NotBilledReason` (`:223-242`), is new and not described. README:25 does not cover it. `AdminStudentSessionSummary` also gained `not_billed`, `not_billed_reason` and `not_billed_note` (`:54-57`).
- [undocumented] `announcements.ts` (session announcements authoring) is not listed under "Current clients".
- [undocumented] `messages.ts` (`/coach/messages`, `/parent/messages`) is not listed.
- [undocumented] `departure-policy.ts` (`/admin/enrollment/departure-policy`, hold, return, stop-all-classes, leaving report) is not listed.
- [undocumented] `pricing.ts` (`/admin/pricing/*`) is not listed.
- [undocumented] `owner.ts` (`/owner/rollup`) is not listed.
