# Verification Fix Plan — Design Spec
**Date:** 2026-05-22
**Source:** Wave 1–5 acceptance checklist manual verification
**Execution model:** 4 parallel agents (A, B, C, D)

---

## Background

A full-stack manual verification run against the local stack (Firebase emulator + MongoDB + FastAPI v2 + Next.js) produced 13 findings across 5 acceptance waves. This spec defines the fixes decomposed into four independently executable workstreams.

---

## Workstream A — Identity, Auth & Tenant Infrastructure

**Scope:** backend only  
**Files touched:** `backend/v2/interfaces/me_routes.py`, `backend/v2/main.py`, `backend/v2/migrations/`, `backend/scripts/seed_local.py`, `scripts/local_test_stack.sh`

### A1 — Expose `membership_id` in `/me` response

**Finding:** `MeResponse` in `me_routes.py` omits `membership_id` even though `AuthClaims` carries it (synthesized by `_LegacyUserMembershipAdapter` as `legacy-{user_id}-{academy_id}`).

**Fix:** Add `membership_id: str | None` to `MeResponse` and pass `claims.membership_id` through. No auth logic changes.

**Acceptance:** `GET /api/v2/me` response includes `"membership_id": "legacy-..."` for all three personas.

---

### A2 — Add `slug` field to `academies` collection

**Finding:** `TenantResolver` looks up academies by `slug` (subdomain) but the collection has no `slug` field. Subdomain resolution always returns `None`.

**Fix:**
1. Write migration `0105_academy_slug.py` (the current last migration is `0104_reporting_snapshot_indexes.py`) that adds `slug` (derived from `_id`, lowercased, dashes preserved) to every existing academy document and creates a unique sparse index on `slug`.
2. Update `seed_local.py` to set `slug: "default-academy"` and `primary_domain: "default-academy.blno.academy"` on the seeded academy.
3. Update `local_test_stack.sh` `start_frontend` to pass `NEXT_PUBLIC_ACADEMY_SLUG=default-academy` so the frontend sends the correct `Host` header or internal tenant header.

**Acceptance:** In SaaS mode, `GET /api/v2/me` with `Host: default-academy.127.0.0.1` (or internal header) resolves tenant and returns 200.

---

### A3 — Wire `BootstrapAcademy` use case to `app.state`

**Finding:** `bootstrap_routes.py` calls `getattr(request.app.state, "bootstrap_academy", None)` which is `None` because the lifespan in `main.py` never sets it.

**Fix:** In `main.py` lifespan:
1. Import `BootstrapAcademy` and its required repositories (`MongoAcademyRepository`, `MongoUserRepository`, `MongoMembershipRepository` or the legacy adapter).
2. Construct and assign `app.state.bootstrap_academy = BootstrapAcademy(...)`.

**Acceptance:** `POST /api/v2/platform/academies/bootstrap` with platform_admin token returns 200 with `academy_id`, `owner_user_id`, `membership_id`, `created: true`.

---

### A4 — Seed a platform_admin user

**Finding:** `_NullPlatformRoleRepository` returns empty for everyone. No user holds `platform_admin`, so bootstrap is always 404.

**Fix:** In `seed_local.py`, after the admin user is created, upsert a `platform_roles` document `{user_id: admin_uid, role: "platform_admin", status: "active"}`. Update the login credentials print to note platform admin.

**Acceptance:** Admin user's `/me` response includes `"platform_roles": ["platform_admin"]`. Bootstrap endpoint returns 200 for admin token.

---

### A5 — Configure `ALLOWED_INTERNAL_TENANT_HEADER` in local stack

**Finding:** The internal header path in `TenantResolver` is inactive because `ALLOWED_INTERNAL_TENANT_HEADER` env var is not set.

**Fix:** Add `ALLOWED_INTERNAL_TENANT_HEADER=x-academy-id` to the backend env block in `local_test_stack.sh` `start_backend`. This enables the `X-Academy-ID` header as a valid tenant resolution mechanism for local/dev testing.

**Acceptance:** In SaaS mode, `GET /api/v2/me` with `Authorization` + `X-Academy-ID: default-academy` returns 200 with correct claims.

---

## Workstream B — Reports KPI + UI Fixes

**Scope:** backend (4 new endpoints) + frontend (2 bug fixes)

### B1 — Reports KPI read-model endpoints

**Finding:** Reports dashboard shows "—" for Active Students, Attendance Rate (30d), Dues Collected (MTD), Pending Waivers. Banner reads "Pre-computed reporting read models are in flight (Wave 5 Agent A)."

**Fix:** Implement 4 aggregate query endpoints under `GET /api/v2/admin/reports/kpis` (single endpoint returning all four, computed on-demand from existing collections):

| KPI | Source | Query |
|---|---|---|
| `active_students` | `enrollments` collection | count distinct `student_id` where `status=active` and `academy_id` matches |
| `attendance_rate_30d` | `attendance` collection | present/(present+absent) in last 30 days for academy |
| `dues_collected_mtd` | `payments` collection | sum `final_amount_cents` where `status=succeeded` and period = current month |
| `pending_waivers` | `waivers` collection | count students with `status != signed` and active enrollment |

The endpoint returns `{ active_students, attendance_rate_30d, dues_collected_mtd, pending_waivers }`. No read model materialisation required — computed inline. Frontend removes the placeholder banner and wires the four cards to this endpoint.

**Acceptance:** Reports page shows real numbers. Banner disappears.

---

### B2 — Fix broken "Coach payouts" nav link

**Finding:** Sidebar link `Coach payouts` navigates to `/admin/coach-payouts` which is a Next.js 404. Correct route is `/admin/payouts`.

**Fix:** Update the sidebar nav config/component to point to `/admin/payouts`.

**Acceptance:** Clicking "Coach payouts" in the sidebar loads the payouts page without 404.

---

### B3 — Hide Firebase UIDs from Payments table

**Finding:** Payments table shows raw Firebase UIDs (e.g. `2YImCLgcQivTcp`) as the parent sub-label under student name.

**Fix:** `AdminPaymentView` in `backend/v2/interfaces/admin/views.py` already has a `parent_name: str | None` field. The fix is in `MongoPaymentRepository.list_for_academy` — the query must join (or `$lookup`) `users` collection to populate `parent_name` from `parent_id`. No view model change is required. The frontend payment row should display `parent_name` instead of `parent_id`; if `parent_name` is already passed through, the fix is frontend-only (replace the UID sub-label with the name field).

**Acceptance:** Payments table shows parent name (e.g. "Manoj Edward") instead of Firebase UID.

---

## Workstream C — Billing Ledger API & Enrollment Events

**Scope:** backend only

### C1 — Enrollment event timeline endpoint

**Finding:** `POST .../enrollments/{id}/pause` and `resume` return 204. There is no queryable event timeline, so the acceptance checklist item "Pause creates event / resume creates event / event timeline visible" cannot be verified.

**Fix:** Add `GET /api/v2/admin/enrollments/{enrollment_id}/events` that returns a chronological list of `EnrollmentEvent` records for the enrollment. The event store is already written by the use cases — this is a read-only projection endpoint.

Response shape (note: the domain model uses `event_type`, not `kind` — the DTO must map from `EnrollmentEvent.event_type`):
```json
{
  "enrollment_id": "...",
  "events": [
    {
      "event_id": "...",
      "event_type": "paused" | "resumed" | "moved" | "withdrawn" | "waitlisted" | "promoted",
      "effective_date": "2026-05-22",
      "actor_id": "...",
      "reason": "...",
      "billing_result": "...",
      "credit_reference": "..."
    }
  ]
}
```

**Acceptance:** After pausing an enrollment, `GET .../events` returns a list with at least one `event_type: "paused"` entry.

---

### C2 — Billing invoice/ledger queryable API

**Finding:** `GET /api/v2/admin/billing` returns 404. There is no endpoint to inspect ledger lines or invoices separately from the flat payments list.

**Fix:** Add `GET /api/v2/admin/billing/invoices` returning invoice-level records with line items:
```json
{
  "invoices": [
    {
      "invoice_number": "INV-202605-BZ4N6N",
      "student_name": "...",
      "period": "2026-05",
      "lines": [{ "description": "monthly fee", "amount_cents": 6000 }],
      "total_cents": 6000,
      "paid_cents": 0,
      "balance_cents": 6000,
      "status": "open"
    }
  ]
}
```

**Acceptance:** Endpoint returns 200 with at least one invoice having `lines` populated.

---

### C3 — Fix `generate-monthly` field name

**Finding:** `POST /api/v2/admin/payments/generate-monthly` requires `period` but callers naturally send `month`. This caused a 422 in testing.

**Fix:** Accept both `period` and `month` in the request body (alias or union). Prefer `period` as the canonical name; accept `month` as a deprecated alias with no breaking change.

**Acceptance:** `POST .../generate-monthly` with `{"month": "2026-05"}` returns 200.

---

## Workstream D — Payout & Enrollment Propagation

**Scope:** backend + `seed_local.py`

### D1 — Seed completed payable occurrences with coach attendance

**Finding:** `GET /api/v2/admin/finance/payouts` returns an empty list. `ComputePayoutUseCase` requires occurrences with `status=completed`, `is_payable=True`, and a `CoachRate` record. None of these exist in the seed.

**Fix:** In `seed_local.py`, after sessions are seeded:
1. For past occurrences (start_at < now), set `status = "completed"` and `is_payable = True`.
2. Seed a `CoachRate` for each coach: `{ coach_id, rate_cents: 2500, effective_from: "2026-01-01" }`.
3. Seed `CoachAttendance` records linking Gowtham and Kishore to their respective past occurrences.

**Acceptance:** `GET /api/v2/admin/finance/payouts` returns at least one payout entry, OR `POST /api/v2/admin/payouts/compute` with a period returns a non-empty statement.

---

### D2 — Fix enrollment validation in `mark_attendance`

**Finding:** When attendance is marked for occurrence `01KS85H1CQ31TJKBBGGDKF2EYX` (Jun 4 occurrence), the system returns `StudentNotEnrolled` even though the student is enrolled in the recurring template. The enrollment lookup checks `session_id == occurrence_id` exactly, not the parent template.

**Root cause:** The seeded enrollment has `session_id = "01KS85H1CP36A3YGP31Y8FJDG7"` (the first concrete session for that template). Future occurrence IDs differ. The `mark_attendance` use case validates enrollment against the literal `session_id` passed in `occurrence_id`.

**Fix (Option 1 — committed):** Add a `template_session_id` field to dated occurrence documents. `mark_attendance` validates enrollment against `session_id == occurrence.session_id OR session_id == occurrence.template_session_id`.

Implementation steps:
1. Write migration `0106_occurrence_template_session_id.py` that backfills `template_session_id` on existing occurrence documents. For the seeded data, each dated occurrence was generated from one of 4 weekly template sessions — the seed script sets `template_session_id` at generation time; the migration applies the same derivation retroactively.
2. Update `seed_local.py` to set `template_session_id` when creating dated occurrence documents.
3. Update `MarkAttendanceUseCase` enrollment check to accept either ID.

This is the confirmed intended design — one enrollment covers all occurrences of a template.

**Acceptance:** Student enrolled in the May 28 session can be marked present in both the May 28 and Jun 4 occurrence of the same template without `StudentNotEnrolled`.

---

## Dependency Map

```
A ──────────────────────────────► A-done
B ──────────────────────────────► B-done
C ──────────────────────────────► C-done
D ──────────────────────────────► D-done
                                    │
                                    ▼
                             smoke re-run (verify all 12 findings cleared)
```

A, B, C, D have no inter-stream dependencies and can run simultaneously.

Post-merge smoke: re-run `scripts/local_test_stack.sh seed` + `smoke`, then re-execute the Wave 1–5 checklist.

**Seed file note:** Both A4 and D1 modify `seed_local.py`. These are in different workstreams — the agent merging both PRs must apply both seed patches sequentially to avoid conflicts on that single file.

---

## Non-goals

- Real `MongoMembershipRepository` (replacing `_LegacyUserMembershipAdapter`) — that is Wave 2 Agent A scope and tracked separately.
- Real `MongoPlatformRoleRepository` — stub in seed is sufficient for local testing; production wiring is separate work.
- Multi-academy seeding — out of scope; requires the real membership repo first.
- Stripe integration testing — fake gateway is correct for local testing.
- Frontend messaging DM end-to-end — exists in API, UI testing deferred.

---

## Acceptance Criteria Summary

All 13 findings from the verification report must be green before declaring the fix wave complete:

| # | Finding | Workstream |
|---|---|---|
| 1 | `membership_id` in `/me` | A1 |
| 2 | Bootstrap unwired | A3 |
| 3 | No platform_admin | A4 |
| 4 | `slug` missing from academies | A2 |
| 5 | `ALLOWED_INTERNAL_TENANT_HEADER` inactive | A5 |
| 6 | Reports KPI placeholder | B1 |
| 7 | Broken nav link | B2 |
| 8 | Firebase UIDs in Payments table | B3 |
| 9 | Enrollment event timeline missing | C1 |
| 10 | Billing ledger not queryable | C2 |
| 11 | `generate-monthly` field name | C3 |
| 12 | `StudentNotEnrolled` on future occurrences | D2 |
| 13 | Coach payout untestable (no data) | D1 |
