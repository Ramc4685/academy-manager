# UIM3 — Funnel / attendance-trends / coach-utilization reports UI
Status: DONE (#362)
Size: M · Depends on: UIC3 (same surface — land UIC3's tab consolidation of /admin/reports first, then add these as extra tabs; if UIC3 slips, add sections to the current page and let UIC3 absorb them) · Tracker: ../TRACKER.md

## User value
Three shipped analytics endpoints have zero frontend callers. Owners get enrollment-conversion, attendance-completion, and coach-utilization insight with no backend work.

## Backend status (verified — routes, DTO fields)
All in `backend/v2/interfaces/admin/reports_routes.py`, persona `admin` (`require_persona("admin")`, wrong persona ⇒ 404):
- `:95` `GET /reports/enrollment-funnel?period=YYYY-MM` (period optional) → `EnrollmentFunnelResponse {leads, applied, assessed, confirmed, dropped, total_applications, conversion_rate: float, period: str | null}` (views.py:1788)
- `:105` `GET /reports/attendance-trends?periods=YYYY-MM&periods=…` (repeated query param, validated by regex; 422 on bad format) → `AttendanceTrendsResponse {periods: [{period, scheduled_count, completed_count, no_show_count, completion_rate}], overall_completion_rate}` (views.py:1799-1809)
- `:118` `GET /reports/coach-utilization?periods=…` (same repeated param) → `CoachUtilizationResponse {coaches: [{coach_id, period, hours: float, payout_minor, utilization_rate}], periods: [str], total_payout_minor}` (views.py:1812-1823)

## Frontend to build (pages/components/queries — concrete)
- Surface: `frontend/app/(admin)/admin/reports/page.tsx` — add three tabs/sections: **Funnel**, **Attendance**, **Coach utilization** (alongside UIC3's Session economics / Dues tabs).
- API client fns in `frontend/lib/api/admin.ts` (or a new `frontend/lib/api/v2/reports.ts` following `lib/api/v2/` pattern):
  - `getEnrollmentFunnel(period?: string)`, `getAttendanceTrends(periods: string[])` (serialize as repeated `periods=` params), `getCoachUtilization(periods: string[])` — all via `apiFetch` from `lib/api/client.ts`; mirror the response types above.
- Query keys in `frontend/lib/query/keys.ts` under `queryKeys.admin`:
  - `enrollmentFunnel: (period?: string) => ["admin","reports","funnel", period ?? "all"]`
  - `attendanceTrends: (periods: string[]) => ["admin","reports","attendance-trends", ...periods]`
  - `coachUtilization: (periods: string[]) => ["admin","reports","coach-utilization", ...periods]`
- UI: funnel = stage bar/step list + conversion-rate stat; attendance = per-period table or line chart of `completion_rate` + overall stat; utilization = table grouped by coach (coach_id → resolve names via existing users query `queryKeys.admin.users("coach")` if available) with hours/payout/utilization columns. Default period selection: last 3 months (client-side date math, reuse the page's existing period picker).
- Client components + TanStack Query v5; read-only, no mutations/invalidation.

## Backend to build (if any — route, use case, tests, manifest registration)
None. No new frontend route (tabs on the existing `/admin/reports` page), so the inventory manifest (`docs/qa/2026-06-28-...manifest.json`) only needs its existing `/admin/reports` entry's `workflows/controls/states/acceptance` lists extended to mention the new tabs — `test_audit_inventory_manifest.py` shape rules require acceptance ≥ workflows ≥ still hold.

## Implementation steps (phased if L; each phase one PR)
1. API fns + query keys + the three tab panels with loading/empty/error states (one PR).
2. Coordinate with UIC3: if UIC3 already merged, add tabs to its tab bar; else gate behind simple section headers so UIC3 can lift them into tabs.

## Files to change/create
- Modify: `frontend/app/(admin)/admin/reports/page.tsx`, `frontend/lib/api/admin.ts` (or create `frontend/lib/api/v2/reports.ts`), `frontend/lib/query/keys.ts`, `docs/qa/2026-06-28-production-scale-local-inventory-manifest.json` (extend `/admin/reports` entry)
- Optionally create: `frontend/components/admin/reports/{funnel,attendance-trends,coach-utilization}-panel.tsx` to keep the page from monolith-growing (audit MT5 concern)

## Verification
- `pnpm typecheck && pnpm lint`; `pytest backend/v2/tests/unit/test_audit_inventory_manifest.py`
- Manual: seed data → each tab renders; empty periods show empty states; invalid period impossible via picker (backend 422 guarded)

## Risks / rollback
- `coach_id` name resolution may need the users list; degrade to showing the id.
- Rollback: tabs are additive to one page; revert the page diff.

## PR checklist (release note · TRACKER.md · plan Status → DONE)
- [x] Release note
- [x] Update TRACKER.md row UIM3
- [x] Plan Status → DONE
