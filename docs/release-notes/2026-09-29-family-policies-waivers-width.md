# Family policies: waiver section matches the other cards' width

PR: #1013

## What changed

- In Settings › Family policies, the embedded "Registration & waivers" section was not width-capped like its sibling cards (`max-w-3xl`), and the waiver screen still used full-page layouts: on a wide screen it ran past the other cards and the template table (`min-w-[780px]`, squeezed into a side-by-side grid) cut off its Actions column.
- The section is now capped at `max-w-3xl`. "Create draft" sits above the templates table instead of beside it, and the table's minimum width drops to 600px, so Template, Status, Registration and Actions (Open / Publish) all fit on desktop. The four status tiles are 2×2 on a phone and 4 across from `md` up.
- Frontend layout classes only (`components/admin/waivers/waivers-management.tsx`, `components/admin/settings/self-service-panel.tsx`). No behaviour, API or data change.

## Deploy notes

- None. Frontend-only; no migration, no config.

## Risk / rollback

- Low: CSS classes only. On a phone the template table still scrolls sideways inside its own card, as it did before.
- Rollback: revert this PR.
