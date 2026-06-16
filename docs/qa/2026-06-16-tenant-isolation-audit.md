# Tenant Isolation Audit

Date: 2026-06-16

## Scope

This audit covers Mongo collections referenced by `backend/v2/`, `backend/scripts/`,
and `scripts/dev/`. The product tenant key is `academy_id`; where the original
request says `tenant_id`, read that as `academy_id` for this codebase.

Enforcement patterns reviewed:

- `backend/v2/shared/tenancy/repository.py` injects `academy_id` into
  `TenantScopedRepository` reads/writes.
- `backend/v2/shared/auth/middleware.py` resolves the request academy and, in
  `single_academy` mode, rejects academy mismatch with 403.
- `backend/v2/tests/test_no_raw_tenant_mongo_access.py` statically guards raw
  tenant-owned Mongo access outside approved infrastructure/composition paths.
- Focused tests added in this hardening branch cover parent, coach, admin,
  reports, invoice artifacts, Stripe portal/webhook, governance, public
  registration, and ledger payment isolation.

## Collection Matrix

Legend:

- Tenant key: `academy_id`, `global`, `platform-global`, or `tenant catalog`.
- Query filter: `base` means `TenantScopedRepository`; `explicit` means direct
  code filters by `academy_id`; `n/a` means intentionally global.
- Index includes tenant: `yes`, `no`, `partial`, or `n/a`.
- Cross-tenant blocked: `yes`, `exception`, or `unclear`.

| Collection | Tenant key | Query filters by tenant | Index includes tenant | Cross-tenant blocked | Exception / notes |
| --- | --- | --- | --- | --- | --- |
| academies | tenant catalog | explicit by `academy_id`/slug/domain | partial | yes | Tenant registry; slug/domain lookup intentionally global-to-tenant resolution. |
| academy_domains | tenant catalog | explicit by domain/academy | partial | exception | Domain-to-tenant resolver data. |
| academy_feature_flags | academy_id | explicit bootstrap/store | unclear | yes | Tenant-owned settings. |
| academy_memberships | academy_id | explicit membership auth | yes | yes | Core auth boundary; indexed `(academy_id,user_id)`. |
| academy_revenue_snapshots | academy_id | base | yes | yes | Reporting snapshot. |
| academy_roles | academy_id | explicit bootstrap/store | unclear | yes | Tenant roles; bootstrap path. |
| academy_settings | academy_id | explicit bootstrap/store | unclear | yes | Tenant settings. |
| account_credit_ledger | academy_id | base/explicit | yes | yes | Credit source unique index includes academy. |
| attendance | academy_id | base/explicit | yes | yes | Parent/coach/admin paths tested. |
| audit_logs | academy_id | explicit | partial | yes | Admin audit hardened to request tenant in this branch. |
| billing_artifacts | academy_id | explicit | unclear | yes | Invoice/payment artifact reads/writes hardened in this branch. |
| billing_calculation_snapshots | academy_id | explicit | yes | yes | Billing proration snapshots. |
| billing_invoice_keys | academy_id | explicit | yes | yes | Monthly billing idempotency key store. |
| billing_policies | academy_id | explicit bootstrap/store | unclear | yes | Tenant billing config. |
| coach_attendance | academy_id | base/explicit | yes | yes | Payout/admin cleanup paths include academy filters. |
| coach_digest_sends | academy_id | explicit | yes | yes | Digest send idempotency by academy/coach/date. |
| coach_payout_snapshots | academy_id | base/explicit | yes | yes | Finance reporting snapshot. |
| coach_rates | academy_id | base/explicit | yes | yes | Coach rates indexed by academy. |
| coach_skill_notes | academy_id | base | yes | yes | Student progress/coaching. |
| credit_applications | academy_id | base/explicit | yes | yes | Invoice credit application. |
| curriculum_video_refs | academy_id | base | yes | yes | Curriculum asset reference. |
| dead_letter_events | academy_id | worker-attributed | partial | exception | Worker queue; event carries academy, dispatcher scans globally. |
| enrollment_events | academy_id | base/explicit | yes | yes | Enrollment event audit. |
| enrollments | academy_id | base/explicit | yes | yes | Parent/coach/admin paths tested; fallback lookup fixed in this branch. |
| event_audit | academy_id | worker-attributed | partial | exception | Dispatcher audit; global worker scan with tenant-attributed event rows. |
| event_handler_runs | event id | worker-global | n/a | exception | Handler idempotency metadata, not tenant data surface. |
| expenses | academy_id | base/explicit | yes | yes | Finance/admin. |
| external_lesson_refs | academy_id | base | yes | yes | Curriculum external refs. |
| idempotency_keys | global key | n/a | no | exception | Keys are globally unique; callers must include tenant/context in key. |
| invoice_lines | academy_id | explicit/base via ledger repo | yes | yes | Invoice detail hardened in this branch. |
| invoices | academy_id | base/explicit | yes | yes | Invoice detail/artifact paths hardened. |
| ledger_payments | academy_id | explicit via ledger repo | yes | yes | Added in this branch; prevents shared legacy `payments` reads. |
| lesson_cards | academy_id | base | yes | yes | Curriculum lesson cards. |
| lesson_plans | academy_id | base | partial | yes | Coach/admin plan data. |
| level_up_recommendations | academy_id | base | yes | yes | Student progress. |
| login_attempts | global identifier/IP | n/a | n/a | exception | Abuse-prevention telemetry; not tenant data. |
| message_campaigns | academy_id | base | yes | yes | Campaign indexes include academy. |
| message_deliveries | academy_id | base | yes | yes | Delivery indexes include academy. |
| messages | academy_id | base | yes | yes | Shared message repository. |
| move_log | academy_id | legacy/seed | unclear | unclear | Legacy seeded collection; v2 launch path should confirm or migrate before relying on it. |
| onboarding_applications | academy_id | base/explicit | yes | yes | Public registration/onboarding. |
| outbox_events | academy_id | worker-attributed | partial | exception | Global worker polling; event payloads carry academy. |
| pause_requests | academy_id | base/explicit | partial | yes | Parent/admin pause workflow. |
| payment_allocations | academy_id | explicit via ledger repo | yes | yes | Ledger allocation indexes include academy. |
| payments | academy_id | base/explicit | yes | yes | Legacy payment aggregate; ledger payments moved out in this branch. |
| payout_audit_log | academy_id | base | partial | yes | Finance audit repository. |
| payout_period_lines | academy_id | explicit via payout repo | yes | yes | Payout line queries include academy. |
| payout_periods | academy_id | base/explicit | yes | yes | Payout period repository extends tenant base. |
| payout_rules | academy_id | legacy/seed | unclear | unclear | Legacy seeded collection; verify before production dependency. |
| payouts | academy_id | base | yes | yes | Legacy finance payout model. |
| platform_audit_events | academy_id optional | platform service | yes | exception | Platform timeline may be global or tenant-attributed. |
| platform_governance_audit_logs | academy_id | explicit governance store | yes | yes | Governance audit indexes include academy. |
| platform_plans | platform-global | n/a | n/a | exception | SaaS plan catalog. |
| platform_roles | platform-global | n/a | n/a | exception | Platform operator roles separate from academy membership. |
| platform_tenant_subscriptions | academy_id | explicit platform billing | partial | yes | One subscription per academy; platform route gated. |
| progress_notes | academy_id | base/explicit | partial | yes | Parent/coach visibility constrained by own child/assigned student. |
| scheduled_enrollment_actions | academy_id | base | yes | yes | Scheduled action repository. |
| session_attendance_snapshots | academy_id | base/explicit | yes | yes | Reporting snapshot. |
| session_feedback | academy_id | base/explicit | yes | yes | Parent/coach feedback. |
| session_occurrence_overrides | academy_id | explicit | unclear | yes | Billing occurrence override lookup. |
| session_occurrences | academy_id | base/explicit | yes | yes | Coach/admin occurrence paths tenant-scoped. |
| session_types | academy_id | base/explicit | yes | yes | Billing session type. |
| sessions | academy_id | base/explicit | yes | yes | Parent/coach/admin paths tenant-scoped. |
| skill_certificates | academy_id | base | yes | yes | Student progress certificates. |
| skill_criteria | academy_id | base | yes | yes | Curriculum criteria. |
| skill_levels | academy_id | base | yes | yes | Curriculum levels. |
| skill_programs | academy_id | base | yes | yes | Curriculum programs. |
| skills | academy_id | base | yes | yes | Curriculum skills. |
| stripe_webhook_events | academy_id | explicit/worker | yes | yes | Dedup/event pipeline; tenant resolution hardened in this branch. |
| student_billing_enrollments | academy_id | base/explicit | yes | yes | Coach billing mutations disabled; admin owns changes. |
| student_data_deletion_requests | academy_id | explicit governance store | yes | yes | Governance indexes include academy. |
| student_level_progress | academy_id | base | yes | yes | Student progress. |
| student_skill_progress | academy_id | base | yes | yes | Student progress indexes include academy. |
| students | academy_id | base/explicit | yes | yes | Parent/coach/admin access tested by relationship. |
| subscriptions | academy_id | base/explicit | yes | yes | Stripe subscription mappings used for tenant resolution. |
| support_access_grants | academy_id | explicit governance store | yes | yes | Service now requires platform admin; revoke tenant-filtered. |
| support_impersonation_requests | academy_id | explicit governance store | yes | yes | Runtime impersonation remains deferred/disabled. |
| tenant_deletion_requests | academy_id | explicit governance store | yes | yes | Governance path; deferred launch workflow. |
| tenant_export_requests | academy_id | explicit governance store | yes | yes | Governance path; export tooling deferred. |
| test_attempts | academy_id | base | yes | yes | Student progress testing. |
| users | global user + legacy academy_id | explicit by uid/email and academy where needed | partial | partial | SaaS auth uses `academy_memberships`; legacy user `academy_id` remains compatibility field. |
| v2_migrations | global | n/a | n/a | exception | Migration registry. |
| waitlist | academy_id | base/explicit | yes | yes | Parent/admin waitlist. |
| waiver_acceptances | academy_id | explicit | partial | yes | Student/parent waiver visibility tenant-scoped. |
| waiver_signatures | academy_id | base/explicit | yes | yes | Waiver signature indexes include academy. |
| waiver_templates | academy_id | explicit/base | yes | yes | Tenant waiver templates. |
| waiver_versions | academy_id | explicit | partial | yes | Waiver version lookup supports legacy rows; verify before SaaS expansion. |
| waivers | academy_id | base | yes | yes | Onboarding waiver records. |

## Findings

1. Green for reviewed launch paths: parent, coach, admin, reports, invoice
   artifacts, Stripe portal/webhook, governance, registration, and ledger
   payment storage now have tenant-scoped regression evidence.
2. Global/platform exceptions are expected for `platform_roles`,
   `platform_plans`, `v2_migrations`, `login_attempts`, domain/tenant resolver
   collections, and worker queues that scan globally but carry `academy_id`.
3. Remaining tenant-audit risk is concentrated in legacy/seed-only or
   compatibility collections: `move_log`, `payout_rules`, `waiver_versions`,
   `session_occurrence_overrides`, and some worker/audit collections with
   partial tenant indexes. These are not current P0 request-path blockers, but
   they should be resolved before broader SaaS/multi-academy expansion.

## Verification Evidence

- `pytest backend/v2/tests/test_no_raw_tenant_mongo_access.py backend/v2/tests/structural/test_saas_production_wiring.py -q` -> passed during hardening.
- `pytest backend/v2/tests/unit/test_admin_composition_tenancy.py -q` -> tenant-scoped audit/invoice/artifact/export regressions passed.
- `pytest backend/v2/tests/contract/test_billing_idempotency.py -q` -> ledger payment isolation and migration audit regressions passed.
- Full backend v2 suite after hardening and ADR-0011 split: `1198 passed, 3 warnings`.
