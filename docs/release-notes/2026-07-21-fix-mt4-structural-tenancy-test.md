# fix-mt4-structural-tenancy-test

PR: (pending)

## What changed
Tightened the existing structural tenancy guard
`backend/v2/tests/test_no_raw_tenant_mongo_access.py` (audit item MT4). It no
longer blanket-exempts the risky directories:

- Removed the wholesale `contexts/*/infrastructure/` exemption — those files
  are now scanned. Access to a tenant-owned collection is allowed only when the
  call site or its enclosing function shows a scoping signal (`academy_id`
  filter/parameter, or the `TenantScopedRepository._scoped(...)` helper).
- Removed `composition/parent.py` and `composition/coach.py` from the
  composition allowlist now that C4 (#317) moved them onto request-time
  `current_academy_id()`. Only `composition/admin.py` (until MT1) and
  `interfaces/admin/progress_routes.py` remain, each with a documented removal
  condition.
- Split the collection list: `users`, `academies`, `academy_memberships`, and
  `academy_domains` are now documented `GLOBAL_COLLECTIONS` (cross-tenant /
  resolved before tenant context) instead of being mislabeled tenant-owned.
- Reaching into another object's `.collection` (bypassing its scoped methods)
  is still flagged; a repository's own `self.collection` is not.

Added self-tests covering: unscoped cross-collection read flagged, `_scoped()`
helper clean, explicit `academy_id` filter clean, global-collection raw access
clean, and foreign `.collection` access flagged.

## Deploy notes
none — test-only change. No production code, migrations, or env changes.

## Risk / rollback
The AST rule is a conservative ratchet, not a security boundary (runtime
correctness stays covered by `TenantScopedRepository` and the C4 behavioural
tests); it may over-approve a function that merely mentions `academy_id`.
Rollback is a single test-file revert with no production impact.
