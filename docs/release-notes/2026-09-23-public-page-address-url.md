# The admin "View page" link accepts the academy address as a full URL

PR: #940

## What changed

- `primary_domain` / `custom_domain` on the academy record now drive the Settings > Public page "View page" link whether they hold a bare host (`riverside.example`) or the same host written as a site root URL (`https://riverside.example/`). Before, a full URL was refused, and the panel said "Your page's web address is not set up yet".
- The link is always built as `https://<host>/`. Values with a path, a port, credentials or a scheme other than http(s) are still refused, and the panel then shows the "not set up yet" note instead of a link.
- Backend only (`GetPublicPageAddress`); no route, DTO or frontend change.

## Deploy notes

- No migration, no index change, no env var. Deploy as normal.

## Risk / rollback

- Low. Only the read-only `public_url` field in `GET/PATCH /api/v2/admin/academy/public-page` is affected, and only for academies whose stored address is a full URL.
- Rollback: revert the PR.
