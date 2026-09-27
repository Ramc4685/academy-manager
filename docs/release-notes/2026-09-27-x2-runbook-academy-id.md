# X2 waitlist runbook: use the production academy ID

PR: #TBD

## What changed

- `docs/runbooks/x2-waitlist-offers-readonly-query.js` filtered on `academy_id: "blno"`, the slug used by local seeds. The production academy_id is `acad_blno_badminton`, so run as written against prod, every section returned nothing and looked like a clean result. It now uses the production ID, with a comment explaining why.
- Run against prod on 2026-09-26 with the correct ID: 1 waitlist offer expired unconfirmed (2026-09-20), 0 `hold_reclaimed` events (no held family lost a seat), and no saved hold-reclaim policy (the default applies).

## Deploy notes

- Docs-only. Nothing deploys, and there is no migration or setting.
- The production API machine has no `mongosh`. Run the queries through a pymongo port over `fly ssh console -a courtmastr-academy-api`, which already has `MONGO_URL` and `DB_NAME` set.

## Risk / rollback

- None. The script only reads (`aggregate()` and `find()`). Rollback: revert this PR.
