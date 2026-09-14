# Stamp governance deletion requests on the subject

PR: #823

## What changed
- Fixes #788 — Governance deletion requests were request-only: the review row recorded the soft-delete policy, but neither the academy nor the student document ever changed, so no roster or admin reader could tell an erasure request was pending.
- `TenantGovernanceService.request_tenant_deletion` and `request_student_data_deletion` now stamp `governance_deletion_status` / `governance_deletion_requested_at` on the subject (academy or student) through two new `TenantGovernanceStore` port methods, `mark_tenant_deletion_requested` and `mark_student_deletion_requested`.
- The stamp is additive and tenant-scoped: it never rewrites an existing stamp and never touches the subject's own lifecycle status. No executor and no cascade are added — the full anonymisation checklist (attendance, absence, makeup, roster, progress, certificates, waivers, messages, digest, audit rows) is documented in `docs/policy/governance-deletion-cascade.md` and referenced from the use case for whoever builds the executor next.

## Deploy notes
- No migrations. The stamp is written lazily via `$set` on first deletion request per subject (academies/students collections); existing documents without the fields are unaffected until a deletion is requested against them.
- No API shape change and no new endpoints.

## Risk / rollback
- Risk: low. The write is additive-only (`$ne` guard prevents re-stamping) and gated behind the existing request-deletion use cases; it does not delete, redact, or cascade anything, so it cannot regress unrelated reads. New unit test coverage in `backend/v2/tests/application/test_tenant_governance.py` pins the stamp-on-request behavior.
- Rollback: revert this PR. No data cleanup is required since the stamp is purely additive metadata.
