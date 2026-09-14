# Governance deletion: what a request does, and what it still owes

Scope: `backend/v2/contexts/platform/governance` — `TenantGovernanceService.request_tenant_deletion`
and `TenantGovernanceService.request_student_data_deletion`.

Tracking issue: [#788](https://github.com/blno-badmintion/academy-manager/issues/788).

## What happens today

Requesting deletion is **request-only**. Two things are written, both reversible:

1. A review row (`tenant_deletion_requests` / `student_data_deletion_requests`) with
   `status: "pending_review"`, the reason, the actor, and a snapshot of the
   `SoftDeletePolicy` / `RetentionPolicy` / `PIIHandlingPolicy` in force at request time.
2. A stamp on the **subject** — the `academies` document, or the `students` document scoped
   by `academy_id` — so any reader can show that an erasure request is pending:

   | field | value |
   | --- | --- |
   | `governance_deletion_status` | `"deletion_requested"` (from `SoftDeletePolicy`) |
   | `governance_deletion_requested_at` | request timestamp (UTC) |

   The stamp is **additive**: it never touches the subject's own lifecycle `status`
   (`active` / `held` / `withdrawn` / …), and a repeat request does not rewrite the first
   timestamp. Un-stamping is not implemented either — a rejected request currently leaves the
   marker in place, and clearing it is part of the executor work below.

Nothing is deleted, redacted, anonymised or cascaded. `hard_delete_allowed` is `False` and
audit plus financial records are preserved by policy.

## What is NOT implemented (the executor's checklist)

There is **no executor**. When one is built, approving a deletion request must walk every
dependent below and either delete, anonymise, or explicitly justify retaining it. Each row
here is currently untouched by any deletion path.

| # | Dependent data | Owning area | Required action | Status |
| --- | --- | --- | --- | --- |
| 1 | Attendance records | attendance | Anonymise student identity; retain counts for coach payroll | NOT IMPLEMENTED |
| 2 | Absence notices | attendance | Delete free-text reasons (parent PII); retain the occurrence | NOT IMPLEMENTED |
| 3 | Makeup credits and bookings | enrollment | Release or void open credits before anonymising | NOT IMPLEMENTED |
| 4 | Class roster entries / enrollments | enrollment | Withdraw and release the seat, then anonymise | NOT IMPLEMENTED |
| 5 | Skill progress and pathway records | coaching | Delete or anonymise; no aggregate depends on identity | NOT IMPLEMENTED |
| 6 | Certificates and awards | coaching | Delete issued artifacts carrying the student's name | NOT IMPLEMENTED |
| 7 | Waivers and consent forms | tenant-ops | Retain per the retention policy, redact PII fields | NOT IMPLEMENTED |
| 8 | Messages and WhatsApp group membership | comms | Remove membership; redact sender/recipient PII | NOT IMPLEMENTED |
| 9 | Parent digest subscriptions and queued sends | comms | Unsubscribe and drop queued sends before the run | NOT IMPLEMENTED |
| 10 | Governance and platform audit rows | platform | **Retain** (`preserve_audit_logs: true`); never cascade a delete here | BY DESIGN |
| 11 | Invoices, payments, credits | billing | **Retain** (`preserve_financial_records: true`); redact contact PII only | BY DESIGN |

Rows 10 and 11 are deliberate retentions, not gaps: `SoftDeletePolicy` preserves audit and
financial history, and `RetentionPolicy` sets the windows (audit and financial records 2555
days; tenant data 30 days after deletion; export artifacts 7 days).

## Rules for whoever builds the executor

- Approval, not the request, is the trigger. A `pending_review` row must never mutate
  dependents.
- Every cascade step goes through its own context's repository or use case — the governance
  context must not reach into another context's collections to delete rows.
- Any background job added for this must be registered in `settings.sentry_cron_jobs`
  (see #751).
- Update this table in the same PR that implements a row, so the checklist never drifts from
  the code.

Related: [`docs/policy/data-retention.md`](./data-retention.md),
`docs/reviews/2026-09-12-lifecycle-completeness.md`.
