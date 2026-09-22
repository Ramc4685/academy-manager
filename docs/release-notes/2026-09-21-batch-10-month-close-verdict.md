# batch-10-month-close-verdict

PR: #870

## What changed

- Fixes #862 — Month close now leads with a one-line verdict instead of a 20-card wall. A new pure `monthCloseVerdict()` reduces the data the admin reports payload already carries (odd-check counts, failed autopay charges, invoices never sent) down to a single headline — either "Sep 2026 is ready to close" or "N things need attention" — with one explanatory line per contributing source underneath. The card wall collapses behind a `CollapsibleSection` so the detail is still one click away, and e2e coverage (`admin-month-close.spec.ts`) exercises both the clean and needs-attention states.

## Deploy notes

Frontend-only change (`frontend/app/(admin)/admin/reports/page.tsx`, `frontend/lib/month-close-view.ts`, new `collapsible-section.tsx`). No migrations, no new environment variables, no backend or API changes.

## Risk / rollback

Low. The verdict is a pure reduction over data the reports page already fetches — no new data sources, no changed endpoints. The detailed cards remain available, just collapsed by default. Full backend gate (pytest, ruff check/format, lint-imports, mypy-baseline) and frontend gate (tsc, eslint, `next build --webpack`) pass on the branch; the 8 pre-existing `test_session_edit_occurrence_orphans.py` failures are unrelated to this change (branch touches no backend files). To roll back, revert this PR's merge commit.
