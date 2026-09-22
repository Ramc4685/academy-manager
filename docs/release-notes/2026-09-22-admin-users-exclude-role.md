# admin-users-exclude-role

PR: #918

## What changed

- `GET /api/v2/admin/users` accepts two new validated query params. `exclude_role=parent` drops a user only when they hold no role other than the excluded one, so a parent who also coaches is kept. `roles=coach&roles=admin` (repeatable) is a union filter over every held role, on both the v2 `roles` array and the legacy scalar `role`. `role`, `roles[]` and `exclude_role` combine with AND; unknown values return 422.
- The list payload now carries `roles` (every held role, primary first) next to the existing primary `role`, which is what the detail endpoint already returned.
- The Mongo query stays tenant-scoped: `academy_id` is the first `$and` clause and each filter is its own clause behind it, never a top-level `$or` across the tenant key. The exclude filter mirrors `_to_domain` for every stored shape (array, scalar-string `roles`, legacy scalar `role`, null, missing, empty array).
- `frontend/lib/api/admin.ts`: `AdminUserView.roles?`, `ListAdminUsersOptions { excludeRole, roles }`, `listAdminUsers(role?, options?)`. No UI change; this is sidebar regroup PR2 and prepares the Staff view in PR3.

## Deploy notes

None. No migration, no index change, no new environment variable. Existing callers of `GET /api/v2/admin/users` and `listAdminUsers(role)` are unchanged; the only visible difference is the additional `roles` field in each list item.

## Risk / rollback

Low. The new params are additive and default to off, so a client that never sends them gets the previous behaviour plus one extra field. If the exclude semantics turn out wrong for some legacy document shape, revert the PR; nothing depends on it yet.
