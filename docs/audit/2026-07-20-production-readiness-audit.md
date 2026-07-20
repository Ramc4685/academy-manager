# Production-Readiness Audit — 2026-07-20

Full-repo audit (architecture / code quality / security) + UI audit. Verified against code; every finding cites file:line actually read. Companion to GAPS.md (2026-07-07), which this largely confirms.

> **Working on a fix?** Every item has a detailed implementation plan under [plans/](plans/) and a status row in [TRACKER.md](TRACKER.md). Update the tracker when an item lands.

## Verdict

**Conditionally ship. Do not rewrite.** Core architecture, tenancy, and money-path code exceed industry standard. Operational gates (typing, observability, rate limiting) are broken or missing. Fix those before scaling; none blocks the current single-academy deployment.

## Scorecard

| Dimension | Rating | Why |
|---|---|---|
| Architecture | Gaps | Layering enforced and holding (import-linter, structural tests, zero cross-context imports across ~810 files). Composition root (6,679 lines) leaks business logic + raw tenant queries outside any enforced boundary. |
| Code quality | Gaps | Code is clean (ruff 0 errors, 2,429/2,429 tests pass in 84s). Gates are not: mypy checks zero files, coverage enforced on `v2/shared` only, no APM/error tracking installed. |
| Security | Meets standard | No exploitable vuln found (OWASP Top 10 / ASVS L2 lens). Webhook/auth/tenant guards strong. Gaps are latent multi-tenant risk + hardening (CSP, rate limiter). |

## Critical (fix before multi-tenant / multi-machine)

1. **Mypy gate is dead.** `backend/__init__.py` + `mypy_path=".."` (`backend/pyproject.toml:29`) makes mypy abort on file 1 ("found twice under different module names"). CI hides it with `continue-on-error: true` (`.github/workflows/production.yml:166-169`). Verified live — zero files checked. ~937 strict errors backlog once fixed (count may be inflated by invocation path; could be ~560).
2. **No error tracking or tracing in production.** `backend/v2/shared/observability/tracing.py:20-29` no-ops — OpenTelemetry isn't in `backend/requirements.txt`. No Sentry anywhere (backend or frontend). Payment failures leave uncorrelated stdout only.
3. **Rate limiter keys on the proxy hop, not the client.** `backend/v2/shared/http/rate_limit.py:86-89` uses `request.client.host`; no `--proxy-headers` (`backend/Dockerfile:14`). Behind Fly + Cloudflare all users share one bucket on registration/onboarding. Fix: key on `Fly-Client-IP`/`CF-Connecting-IP` with trusted-hop check.
4. **Parent reads bind `academy_id` at boot, not per-request.** `backend/v2/composition/parent.py:721` (list_payments), `:832-920` (children/enrollments) close over the startup value; `parent.py:646` shows the correct request-time `current_academy_id()` pattern. Same residue in coach writes (`composition/coach.py`, GAPS.md #1). Cross-tenant leak the moment `APP_TENANCY_MODE=multi_academy` flips.

## Quick wins (minutes–hours, no design change, do first)

| # | Fix | Effort | Where |
|---|---|---|---|
| 1 | Move pnpm `overrides` out of the ignored `"pnpm"` key — esbuild/undici/ws security pins currently do nothing (pnpm 11 ignores the field, verified live) | 5 min | `frontend/package.json` |
| 2 | Delete `backend/__init__.py` (or fix `mypy_path`) to un-break mypy | 15 min + triage | `backend/__init__.py` |
| 3 | Replace `ADMIN_PASSWORD=Admin@12345` with `CHANGE_ME` | 2 min | `backend/.env.example:12` |
| 4 | Delete orphaned `backend/routers/`, `backend/services/` (.pyc-only), `backend/.env.bak`, empty `backend/tests/` | 10 min | repo root |
| 5 | Add `Content-Security-Policy` + `Strict-Transport-Security` headers | 30–60 min | `frontend/next.config.ts:30-38` |
| 6 | Fix local `pnpm typecheck` (stale `.next/types` for deleted route; fails locally, passes only in fresh CI builds) | 15 min | `frontend/tsconfig.json:22` |
| 7 | Widen coverage gate from `v2/shared` to `v2` | 15 min | `.github/workflows/production.yml:128` |
| 8 | Dedupe `mapRoleToStatus` (copied twice, both `any`-typed) | 10 min | `frontend/app/(admin)/admin/users/page.tsx:73`, `AdminUsersDirectory.tsx:259` |
| 9 | Move tracked repo-root clutter (png, financial-flows html, Plans.md, `output/`) to docs/ or gitignore | 15 min | repo root |
| 10 | Add Mongo lease around scheduler job bodies (pattern already correct in outbox dispatcher) | ~1 hr | `backend/v2/main.py:262-283` vs `shared/events/dispatcher.py:104-149` |

## Medium-term improvements

- **Drain the composition root**: money math (`_money_to_cents` admin.py:707, `_invoice_outstanding_cents` :799), payout eligibility (:3220-3292), KPI pipelines (`_make_reports_kpis` :596) → move into `contexts/billing/application`; add an import-linter contract for `composition/`.
- **Split runtime vs dev requirements**: 136-package pip-freeze into the prod image incl. confirmed-unused `boto3`, `huggingface_hub`, `tiktoken`, `google-genai` + dev tools.
- **Real-auth e2e in CI**: all CI Playwright runs use `NEXT_PUBLIC_E2E_AUTH_BYPASS=1`; `playwright.local-auth.config.ts` exists but isn't in CI. One emulator-backed login→redirect smoke closes it.
- **Structural tenancy test**: 11 Mongo classes sit outside `TenantScopedRepository` (spot-checked correct; several legitimately global). Add the structural test AGENTS.md promises; extend to `composition/`.
- **Split frontend monolith pages when next touched**: `admin/students/[studentId]/page.tsx` 3,026 lines / 23 hooks; `sessions/[id]` 2,226; `payments` 1,822.

## What's strong (keep)

Machine-enforced DDD layering that actually holds; `TenantScopedRepository` + ContextVar tenancy; Stripe webhook path (multi-secret signature verify, event-id dedup, amounts only from verified payload); Firebase `check_revoked=True` with prod refusing the fallback; behavioral test suite (in-memory fakes, contract tests on real composition closures, wrong-persona-404 coverage); single DomainError→HTTP mapping; CORS wildcard rejected at boot; no secrets in tree or history.

## Not re-verified (needs confirmation)

- Resend email HTML escaping (`resend_send_port.py:36-42` passes body as HTML; user-field escaping untraced).
- `stripe==15.1.0` pin vs `client.v2.core.accounts.create` API shape (GAPS.md #11).
- Platform-charge fallback parking academy funds on platform account (GAPS.md #4).
- `python-jose`/`ecdsa` CVE exposure (legacy seed-path deps).
- Duplicate migration prefixes `0070_*`/`0145_*` ordering safety (GAPS.md #10).
- Admin billing DTOs `extra="ignore"` + bounds on money fields.

---

# UI Audit

71 pages: 41 admin, 10 coach, 9 parent, 9 marketing/shared/auth. Admin nav = 24 items in 3 groups (`components/admin/screen-meta.ts:45-89`) — at its scaling limit. Coach/parent bottom navs (4 tabs) are fine.

## What can be COMBINED (ranked)

| # | Merge | Why | Effort |
|---|---|---|---|
| 1 | `/admin/coaches` + `/admin/parents` + `/admin/users` → one directory with role tabs | All three render the same `AdminUsersDirectory` component; `/admin/users` is the superset and isn't even in nav | S |
| 2 | `/admin/pause-requests` → 5th tab of `/admin/requests` | `/admin/requests` is already a 4-tab approval queue (makeups/trials/absences/cancellations); pauses are the identical approve/decline pattern | S |
| 3 | `/admin/session-economics` + `/admin/dues` → tabs of `/admin/reports` (billing-health can stay separate as ops diagnostic) | Four top-level nav items, all read-only financial analytics on the same ledger data | M |
| 4 | `/admin/coach-payslip` → tab/drawer of `/admin/payouts` | Payslip (109L) is a per-coach shaping of payout data | S |
| 5 | `/admin/students/[studentId]/progress` → third tab of student detail (tabs `overview`/`billing` already exist at line 83-100). Same for coach `sessions/[id]/skills` + `/progress` → tabs of coach session detail | Same data source, same intent | S |
| 6 | `/admin/registrations` + `/admin/waitlist` + orphaned `/admin/level-up-queue` → one "Admissions/Queues" screen | Three small approval-queue pages (99/159/220L) with identical list-approve UX; rescues the orphan | M |
| 7 | `/admin/settings/self-service` → section of `/admin/settings` (65L) | Currently a separate top-level nav item for a settings child | S |
| 8 | Delete/redirect `(shared)/calendar` (38L) and `(shared)/messages` (41L) stubs | They only render a link to the real persona screen | S |

**Orphans (no inbound link):** `admin/level-up-queue`, `parent/attendance`, `admin/users` (hidden superset). **Alias:** `admin/dashboard` → `/admin` redirect.

## What's MISSING (backend exists unless noted) — ranked by user value

| # | Gap | Frontend to create | Backend | Size |
|---|---|---|---|---|
| 1 | **Platform/tenant admin persona — entire domain dark** | New `(platform)` route group: tenant list/detail (lifecycle, plan, health), platform billing, governance (exports/deletions/support-access/impersonation), audit viewer, Connect onboarding trigger | EXISTS: ~35 routes in `backend/v2/interfaces/platform/` (5 route files); flag `enable_platform_routes` forced off in prod single-academy (`settings.py:234-239`) | L |
| 2 | **Real TenantSwitcher** | Swap stub in `frontend/lib/api/v2/memberships.ts` (TODO wave5-A, lines 37-46) for a real call; TenantContext already handles multi-academy shape | **NEEDS NEW ROUTE**: `GET /me/memberships` in `me_routes.py` (repo method `list_memberships_for_user` exists) | S |
| 3 | **Reports: enrollment-funnel, attendance-trends, coach-utilization** | 3 tabs/sections on `admin/reports` | EXISTS: `admin/reports_routes.py:95,105,118` — zero frontend callers | M |
| 4 | **Session-type management** | Settings section or page (CRUD) | EXISTS: `admin/session_type_routes.py:40-94` — dark | S |
| 5 | **Billing-enrollment move/override** | Admin actions on student detail; coach move-preview flow | EXISTS: admin `session_type_routes.py:109,133`; coach `billing_enrollment_routes.py:98,150,199` — dark | M |
| 6 | **Bulk user invite** | CSV/multi-email modal on users directory | EXISTS: `admin/directory_routes.py:121` — dark | S |
| 7 | **Coach skill-notes** | Notes panel on coach student passport | EXISTS: `coach/skill_routes.py:506,529` — dark | S |
| 8 | **Tuition-discounts report** | Table in reports/dues | EXISTS: `admin/billing_routes.py:717` — dark | S |
| 9 | **Platform-fallback billing setting** | Settings card (visibility for GAPS.md #4 money-parking risk) | EXISTS: `admin/billing_routes.py:104,122` — dark | S |
| 10 | **Curriculum authoring extras** (place-in-level, external-refs, seed content) | Buttons/forms on `admin/pathway` | EXISTS: `admin/progress_routes.py:111`, `pathway_routes.py:290,318` — dark | S |
| 11 | **Franchise cross-academy rollup** | New page (consolidated financials) | **MISSING BOTH SIDES**; depends on #2 + `enable_owner_role` flag | L |
| 12 | **Student login persona** | Everything — no `(student)` group | **MISSING BOTH SIDES**: `enable_student_login` flag is inert; no `interfaces/student/` package | L |
| 13 | **Real shared Messages inbox / Calendar** | Replace the two shell pages | Partial: admin send-side exists; **no recipient-facing message-read routes** (new backend needed). Calendar can compose existing schedule endpoints | M/L |

**Dead backend routes (no callers — delete or wire):** `parent/enrollment_routes.py:30,64` (`POST /parent/billing-enrollments` + `/cancel`) — parent flows go via checkout/self-cancel instead. Otherwise every live frontend call maps to an existing backend route (verified).

**Not gaps (verified working):** billing-health/quarantine replay UI, owner financial dashboard (PR #295), invoice itemisation seam (PR #299), coach payroll UI.

## Design/UX standardization (do in this order)

1. **Tokens single-source + contrast fixes.** Rally palette defined 3× (`tailwind.config.ts:26-47`, `globals.css:31-40`, raw hex in components). While consolidating, fix AA failures: `#94a3b8` (rally-subtle) on light ≈ 2.9:1; admin sidebar micro-text `#475569`/`#64748b` on `#0a0f1c` ≈ 2.5-3.7:1 at 9px (`(admin)/layout.tsx:189,211,277`).
2. **De-hex the design system itself.** `components/ds/button.tsx:39-65` hardcodes every variant color inline — until fixed, every DS adoption spreads hex.
3. **Add missing DS primitives:** Input/FormField (label + `aria-describedby`), Skeleton, EmptyState, Modal (focus trap + Escape + focus-return — currently zero focus traps repo-wide), Toast (**no mutation feedback system exists**; success/error is inline `<p role="alert">` per page).
4. **Migrate the parent surface.** 234 of 404 inline-style occurrences live in 6 parent files (`progress` 58, `payments` 54, `children` 43, `requests` 40, `dashboard` 39, `waivers` 24). Highest-leverage sweep; do NOT start before 1-3.
5. **Add a desktop Chromium Playwright project.** CI only runs mobile viewports (`playwright.config.ts:49-54`); the admin `lg:` sidebar branch is never exercised.
6. **Independent polish:** server-side role gating (kills redirect flash; add role check to `(shared)/layout.tsx:17-19`), admin nav restructure (collapse groups; consolidations above remove ~6 items), align manifest theme colors (`#0a0a0a` matches nothing). ~~delete unused `lib/offline/*`~~ — CORRECTED 2026-07-20: `lib/offline` is imported by `app/(coach)/layout.tsx:10` and `coach/needs-review/page.tsx:5-6` and guarded by `coach-offline-writes.spec.ts`; not dead code. See TRACKER.md corrections.

**Monolith split map (mechanical — boundaries already exist as internal functions):**
- `admin/students/[studentId]/page.tsx` (3026L): extract BillingWorkflowPanel (:628-1282), 4 billing dialogs (:1928-2314), SessionsPanel (:1283+), StudentEditForm (:2459+).
- `admin/sessions/[id]/page.tsx` (2226L): extract Roster/Waitlist tables + 7 workflow dialogs (:667-2065).
- `admin/payments/page.tsx` (1822L): extract ReconciliationReportPanel (:676-813) + 6 dialogs (:884-1710).
- Shared dialog chrome (`RallyDialog`, `DialogActions`, `Field`, `Th`, `TableSkeleton`) is duplicated across all three — belongs in `components/ds`.

## UI: what's already good

Typed `ApiError` → `role="alert"` error banners end-to-end; admin responsive layout (real sidebar/drawer split, not stretched mobile); consistent table `overflow-x-auto` (24/24); textbook service-worker update flow with user-initiated refresh; coherent visual identity (the problem is triplicated implementation, not taste).
