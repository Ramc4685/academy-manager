# api-contract-followups

PR: #1153

## What changed
Two more admin money endpoints now declare their response shape, so the frontend contract check covers them. `POST /admin/payments/refund` returns the refund result type the use case already produced, and `GET /admin/billing/invoices/{id}/audit` returns typed audit entries. The audit view copies the billing domain's audit entry, because the API layer may not import the domain directly. A structural test fails if the two drift apart. Both endpoints are added to `frontend/lib/api/billing-contract.ts`. The responses on the wire are unchanged.

`scripts/dev/pre-push-checks.sh` now writes each check's output to its own temp file instead of the shared `/tmp/pre-push-out`, so gates running at the same time in different worktrees no longer overwrite each other's failure output.

Invoice creation (`POST /admin/students/{id}/invoices` and the bill-period route) is still untyped. Typing it means building a view of the full invoice document, and a wrong field there would turn a successful invoice into a 500.

The real-backend journeys fixture looked up the seeded coach from `GET /admin/sessions` with no date, which lists only today's sessions. The seeded coach teaches only on Thursdays, so the journeys failed every other day, and they now block CI Gate. The fixture asks for the upcoming 30-day window instead.

The coach-attendance journey opened the coach session page without `?date=`, so the page used the browser's date. On a UTC runner that is already tomorrow during the academy's evening, and the page showed "Session not found". The journey now passes the academy date, the same way the app's own links do.

The SaaS coach-attendance spec now stubs `GET /coach/ai/status`, which #1142 added to coach Today. Unstubbed, the call returned 502 and sometimes reached the console check, so the spec flaked on Chromium and WebKit.

## Deploy notes
Nothing to run. The OpenAPI snapshot and generated frontend types are regenerated.

## Risk / rollback
If a real audit entry ever lacked a required field, the audit endpoint would now return a 500 instead of a partial row. The real lister dumps the domain model, which requires those fields. Roll back by reverting the PR.
