## frontend/lib/api/v2/README.md

- [stale-not-built] README:25 says `students.ts` calls "admin student progress and placement endpoints"; `students.ts` has no progress or placement calls. It covers student detail (`students.ts:127,153`), invoices (`:166`), and enrollment transfer, tuition-discount and fee (`:185,211,223,253`).
- [stale-not-built] README:24 says `sessions.ts` calls "admin session and occurrence endpoints". It only calls `/admin/session-occurrences/*` coach-attendance, coach and replacement (`sessions.ts:28,37,46`). There are no session endpoints.
- [contract] README:27-28 says `GET` returns active types only. `listSessionTypes` accepts `includeArchived` and sends `?include_archived=true` (`session-types.ts:54-60`), so archived types can be listed through this client.
- [contract] README:29-31 says `memberships.ts` derives a single active academy from `/me` because `/me/memberships` is not exposed yet. The code calls `GET /me/memberships` directly (`memberships.ts:45`). The only fallback left is a placeholder academy name (`memberships.ts:46-52`, `deriveAcademyLabel`).
- [undocumented] `announcements.ts` (session announcements authoring, `:62,72,83`) is not listed under "Current clients".
- [undocumented] `messages.ts` (`/coach/messages`, `/parent/messages` inbox and mark-read, `:39-54`) is not listed.
- [undocumented] `departure-policy.ts` (`/admin/enrollment/departure-policy`, hold, return, stop-all-classes, leaving report, `:29-145`) is not listed.
- [undocumented] `pricing.ts` (`/admin/pricing/*`, `:77-184`) is not listed.
- [undocumented] `owner.ts` (`/owner/rollup`, `:38`) is not listed.
