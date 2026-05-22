# SaaS Data Governance And Support Access

Date: 2026-05-22

Status: Initial v2 platform governance contract

Scope:

- Tenant export request policy.
- Tenant deletion request policy.
- Student data deletion request policy.
- Support access grants.
- Support impersonation audit model.

## Decision

SaaS data governance belongs to the v2 platform context:

```text
backend/v2/contexts/platform/governance/
```

It must not be implemented in parent tuition billing, academy admin business
workflows, or legacy `/api/*` routes.

## Policies

### Tenant export

- Tenant export starts as a queued request.
- Exports redact PII by default.
- Explicit PII inclusion must be captured on the request.
- Export artifacts are short-lived and governed by the retention policy.
- Every request writes an audit row.

### Tenant deletion request

- Tenant deletion starts as `pending_review`.
- The first action is a soft-delete transition request, not hard deletion.
- Audit logs and financial records are preserved.
- Hard deletion is not allowed by the initial application use case.

### Soft delete

- Tenant soft delete marks the tenant as `deletion_requested`.
- Student soft delete marks the student as `deletion_requested`.
- Soft delete policy preserves audit logs and financial records.

### Retention

- Tenant data retention after deletion request: 30 days.
- Export artifact retention: 7 days.
- Audit log retention: 2555 days.
- Financial record retention: 2555 days.
- Support access audit retention: 2555 days.

### PII handling

- PII is redacted from exports by default.
- Student PII fields include name, date of birth, medical notes, and parent
  contact information.
- Parent PII fields include name, email, phone, and billing contact
  information.
- Minor student profiles are not deleted without review.

### Student data deletion

- Student deletion starts as `pending_review`.
- The initial request redacts student PII and does not hard-delete the student
  profile.
- The request is scoped by `academy_id` and `student_id`.
- Every request writes an audit row.

### Support access

- Support access requires a platform role: `platform_support` or
  `platform_admin`.
- Support access is time-bound.
- The purpose must be recorded.
- Every grant writes an audit row.

### Support impersonation

Full impersonation is not enabled yet.

The current model records an impersonation request with:

- `impersonation_enabled = false`
- `approval_required = true`
- `session_token = null`
- `status = requires_manual_approval`

This allows support workflows to become auditable before the product has a safe
impersonation runtime. A future implementation must add approval, session
scoping, visible user banners, action restrictions, and automatic expiry before
minting any impersonation session.

## Required Audit Fields

Platform/support audit rows must include:

- `actor_user_id`
- `actor_membership_id`
- `actor_platform_role`
- `academy_id`
- `action`
- `entity_type`
- `entity_id`
- `before_snapshot`
- `after_snapshot`
- `request_id`
- `ip_address`
- `created_at`

For platform support actions, `actor_membership_id` may be null only when
`actor_platform_role` is present.

## Remaining Gaps

- Mongo infrastructure repositories are not wired yet.
- No platform BFF routes are exposed yet.
- No export artifact generation worker exists yet.
- No tenant deletion approval or execution workflow exists yet.
- No safe runtime impersonation exists yet.
