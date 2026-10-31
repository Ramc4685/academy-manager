# Academy mark in the app shells, per-host title and login header, sport-neutral credit

PR: #998

## What changed

- Rows 14, 15 and 35 of the hardcoded-values cleanup, as a follow-up to #992.
- The admin, parent and coach shells show the academy's own mark instead of the shuttlecock / "Academy" wordmark. The mark is the logo when it is an https URL, otherwise a name monogram, and the colour is hex-validated.
- New coach-gated `GET /api/v2/coach/academy`, scoped to the request academy.
- On academy hosts, the browser title, apple-web-app title and login/register header show the academy name. The platform host keeps "CourtMastr".
- The public footer credit and the OG card credit use a sport-neutral CourtMastr mark.

## Deploy notes

- No migration and no new env vars.
- Adds one backend route: `GET /api/v2/coach/academy`.

## Risk / rollback

- Low. The changes are cosmetic chrome, plus one read-only route that returns the request academy's name, logo and colour.
- BLNO's staff and parents will see BLNO's name/logo in the header.
- Rollback: revert this PR's merge commit.
