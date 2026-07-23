# fix-uic6-admissions-queues

PR: #TBD

## What changed
Registrations, the global waitlist, and the coach level-up queue are now one
**Admissions** screen at the canonical route `/admin/registrations`, with
tabs for Registrations (default) · Waitlist · Level-ups and a `?tab=` deep
link, following the same tablist pattern as `/admin/requests`. This rescues
`/admin/level-up-queue`, which had zero inbound links anywhere in the app.

- `/admin/waitlist` is now a server redirect to
  `/admin/registrations?tab=waitlist`.
- `/admin/level-up-queue` is now a server redirect to
  `/admin/registrations?tab=level-ups`.
- Each screen's body moved verbatim into
  `components/admin/admissions/{RegistrationsTab,WaitlistTab,LevelUpsTab}.tsx`,
  keeping the same query keys, mutations, and data-testids
  (`admin-registrations-tab`, `admin-waitlist-tab`, `admin-level-up-queue-tab`)
  so existing selectors and behavior are unchanged.
- `components/admin/screen-meta.ts`: the standalone "Waitlist" nav item and
  its topbar metadata were removed; "Registrations" is retitled "Admissions"
  (net −1 nav item, and level-ups become reachable for the first time).
- The `[applicationId]` registration review flow is untouched; it still
  lives at `/admin/registrations/[applicationId]`.

Audit item UIC6.

## Deploy notes
none — frontend-only IA move. All three backend APIs
(`/admin/registrations`, `/admin/waitlist`, `/admin/level-up-queue`) are
unchanged.

## Risk / rollback
Low: pure frontend move; mutations and endpoints untouched. e2e updated —
`admin-shell.spec.ts` and `saas-launch-route-matrix.spec.ts` route smoke
rows now point at the tab URLs, plus a level-up-queue stub route was added.
`admin-registrations.spec.ts` and the `[applicationId]` detail coverage in
`local-auth-inventory.spec.ts` pass unchanged since that route wasn't
touched. The level-up tab is newly discoverable — expect real traffic to a
previously dark screen; its empty/error states were already handled by the
existing component. Rollback = revert the single PR (three standalone pages
and the old nav item restored).
