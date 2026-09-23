# People CRM Families view: /admin/families reads the family index

PR: #0000

## What changed

- `/admin/families` is now the People CRM Families view (engineering-spec §3.2). It reads the new family index (`GET /api/v2/admin/families`) instead of Billing Setup, so it shows one row per family: the parent with tappable phone and email, each child with their lifecycle chip (the same labels as the Students page), the rolled-up family stage, card and login state, and the balance with any overdue amount.
- Scope tiles (Families, Active, Leaving, Left) come from `GET /api/v2/admin/families/summary` and count the whole academy, not just the rows loaded. If the summary fails the tiles show a dash and an error with Retry, never a zero.
- Filters run on the server and are kept in the URL, so a filtered list can be bookmarked or shared: preset chips (All, Active, Leaving, Left, Overdue, No card) are on/off toggles applied on click; a Class filter lists the academy's classes; search waits until typing stops, then matches parent and child names, email and phone. When the search matches a child, that child is the result row and links straight to the child's page.
- Family, Children, Stage and Balance columns sort on the server (click again to reverse; screen readers hear the sort direction). Sorting now covers every family, not only the pages already loaded, which replaces the old "Owes money" toggle and "Owed, highest first" sort.
- Money is shown only when the server returns it: with no money access there is no Balance column, no Overdue chip and no amounts. A balance the server could not read shows as unknown with a warning, never $0.00.
- A family whose parent has no login account ("No account") is shown without a link, because it has no Billing page to open.
- The "Invite all not invited" bulk action stays. It now collects every not-invited family across all pages of Billing Setup (up to a cap), not just the rows on screen, and sends through the same per-family invite as before.
- No new route. `/admin/parents` still lands on `/admin/families?view=families`, and the page leaves that URL alone until a filter changes.

## Deploy notes

- Frontend only. It needs the family index backend (`GET /admin/families` and `/admin/families/summary`) deployed first or in the same release; without it the list shows its error state with Retry.
- No migration, no feature flag, no environment variable.

## Risk / rollback

- Low to medium. The page is read-only apart from the existing bulk invite. The visible change: the list's columns and filters are different, the old autopay-count and "invited on" columns are gone from the list (still on each family's page), and the list numbers can lag the Billing tab by up to 60 seconds because of the backend cache.
- Not built yet (later slices): multi-select, bulk Message with recipient count, CSV Export, saved Groups, last contact and next follow-up columns, tags, and the Not attending / Missing info / Needs attention chips.
- Rollback: revert the PR. The backend routes stay and are harmless unused.
