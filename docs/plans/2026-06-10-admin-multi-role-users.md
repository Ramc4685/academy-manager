# Admin Multi-Role Users Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Allow one academy user account to hold multiple app roles, especially `parent` + `coach`, and let admins manage those roles without manual database updates or duplicate email accounts.

**Architecture:** Treat `roles` as the app access source of truth and keep the legacy scalar `role` as a compatibility/display field only. Admin role management must update both `users.roles` and `academy_memberships.roles` so current non-SaaS auth and future SaaS membership auth stay consistent. Session coach assignment remains a scheduling relationship and must not grant app login access by itself.

**Tech Stack:** FastAPI, Pydantic, MongoDB/Motor, Firebase-backed identity records, Next.js 15 App Router, React 19, TanStack Query, Tailwind, existing v2 admin BFF.

---

## Current Behavior Found

- `frontend/lib/api/me.ts` already routes multi-role users by priority: `admin`, then `coach`, then `parent`.
- `frontend/app/post-login/page.tsx` calls `/me` after Firebase login and redirects to `homeForRoles(currentUser.roles)`.
- `backend/v2/interfaces/me_routes.py` returns `AuthClaims.roles`.
- In current production config, `V2_SAAS_MODE` is not enabled in `backend/fly.toml`, so auth uses the legacy `users.roles` projection through `_LegacyUserMembershipAdapter`.
- `backend/v2/contexts/identity/infrastructure/mongo_user_repo.py::change_role()` currently replaces the role array with exactly one role: `{"role": role, "roles": [role]}`.
- Admin session coach pickers call `listAdminUsers("coach")`, so a parent assigned as a session coach still needs the `coach` app role to authenticate and appear cleanly in coach/admin flows.

## Desired Behavior

- One email can be both a parent and a coach.
- Admin can grant/revoke `parent`, `coach`, and `admin` roles from the admin user UI.
- A `parent + coach` user logs in and lands on the coach home by default because existing role priority already prefers coach over parent.
- A multi-role user can still access every route matching any assigned role.
- Role updates are audited with actor, reason, before roles, and after roles.
- Role updates keep `users.roles`, `users.role`, and `academy_memberships.roles` synchronized.

## Non-Goals

- Do not infer app roles from session assignments.
- Do not create separate Firebase users for the same person.
- Do not migrate legacy `/api/*` role handling.
- Do not redesign the full admin settings access matrix in this slice.
- Do not introduce fine-grained roles such as owner, senior coach, or limited admin.

## Role Rules

- Valid roles: `admin`, `coach`, `parent`.
- `roles` must contain at least one role.
- Duplicate roles are removed while preserving deterministic order.
- Legacy primary `role` should be derived by priority:
  1. `admin`
  2. `coach`
  3. `parent`
- Admins cannot remove their own `admin` role through this endpoint.
- If a user has linked students, removing `parent` should be blocked unless a future reassignment flow is implemented.
- If a user is assigned to active sessions, removing `coach` should be blocked unless a future reassignment flow is implemented.

## Backlog Links

- Local backlog: `docs/tickets/post-mvp-admin-multi-role-backlog.md`
- GitHub issues: linked from the local backlog after issue creation.

---

### Task 1: Backend Multi-Role Role Update Use Case

**Files:**
- Modify: `backend/v2/contexts/identity/application/change_user_role_use_case.py`
- Modify: `backend/v2/contexts/identity/application/use_cases/admin_directory.py`
- Modify: `backend/v2/contexts/identity/infrastructure/mongo_user_repo.py`
- Test: `backend/v2/tests/application/test_admin_user_edit.py`

**Step 1: Write failing tests for preserving multiple roles**

Add tests to `backend/v2/tests/application/test_admin_user_edit.py`:

```python
async def test_change_user_roles_preserves_parent_when_granting_coach() -> None:
    repo = FakeAdminUserRepo(
        role="parent",
        roles=("parent",),
        linked_student_count=1,
        session_count=0,
    )
    use_case = ChangeUserRoles(repo)

    result = await use_case.execute(
        "user-1",
        ChangeUserRolesCommand(
            roles=("parent", "coach"),
            actor_id="admin-1",
            reason="Coach also has a child enrolled",
        ),
        academy_id="academy-1",
    )

    assert result.role == "coach"
    assert result.roles == ("parent", "coach")
    assert repo.role_commands == [
        {
            "actor_id": "admin-1",
            "reason": "Coach also has a child enrolled",
            "roles": ("parent", "coach"),
        }
    ]
```

Also add:

```python
async def test_change_user_roles_rejects_empty_roles() -> None: ...
async def test_change_user_roles_blocks_removing_parent_with_linked_students() -> None: ...
async def test_change_user_roles_blocks_removing_coach_with_active_sessions() -> None: ...
```

**Step 2: Run tests to verify failure**

Run:

```bash
cd backend
source .venv/bin/activate
pytest v2/tests/application/test_admin_user_edit.py -q
```

Expected: failure because `ChangeUserRoles` and `ChangeUserRolesCommand` do not exist.

**Step 3: Add the use case and protocol**

In `backend/v2/contexts/identity/application/change_user_role_use_case.py`, keep `ChangeUserRole` for compatibility and add:

```python
class AdminRolesWriter(Protocol):
    async def change_roles(
        self,
        user_id: str,
        roles: tuple[Role, ...],
        *,
        academy_id: str,
        actor_id: str,
        reason: str,
    ) -> AdminUserDetail | None: ...


class ChangeUserRolesCommand(BaseModel):
    model_config = {"frozen": True}

    roles: tuple[Role, ...] = Field(min_length=1)
    actor_id: str = Field(min_length=1)
    reason: str = Field(min_length=1, max_length=500)


class ChangeUserRoles:
    def __init__(self, users: AdminRolesWriter) -> None:
        self._users = users

    async def execute(
        self,
        user_id: str,
        command: ChangeUserRolesCommand,
        *,
        academy_id: str,
    ) -> AdminUserDetail:
        roles = _normalize_roles(command.roles)
        updated = await self._users.change_roles(
            user_id,
            roles,
            academy_id=academy_id,
            actor_id=command.actor_id,
            reason=command.reason,
        )
        if updated is None:
            raise UserNotFound("user not found")
        return updated
```

Add `_normalize_roles()` in the same file:

```python
def _normalize_roles(roles: tuple[Role, ...]) -> tuple[Role, ...]:
    priority: tuple[Role, ...] = ("admin", "coach", "parent")
    selected = set(roles)
    return tuple(role for role in priority if role in selected)
```

**Step 4: Add repository method**

In `MongoUserRepository`, add:

```python
async def change_roles(
    self,
    user_id: str,
    roles: tuple[Role, ...],
    *,
    academy_id: str,
    actor_id: str,
    reason: str,
) -> AdminUserDetail | None:
    now = datetime.now(UTC)
    before = await self.collection.find_one(
        {"academy_id": academy_id, **self._id_filter(user_id)}
    )
    if before is None:
        return None

    canonical_user_id = self._to_domain(before).user_id
    primary_role = _primary_role(roles)

    linked_student_count = await self._linked_student_count(academy_id, before)
    session_count = await self._active_session_count(academy_id, before)
    old_roles = set(self._to_domain(before).roles)
    new_roles = set(roles)
    if "parent" in old_roles and "parent" not in new_roles and linked_student_count > 0:
        raise UserRoleChangeBlocked("cannot remove parent role while students are linked")
    if "coach" in old_roles and "coach" not in new_roles and session_count > 0:
        raise UserRoleChangeBlocked("cannot remove coach role while active sessions are assigned")

    doc = await self.collection.find_one_and_update(
        {"academy_id": academy_id, **self._id_filter(user_id)},
        {"$set": {"role": primary_role, "roles": list(roles), "updated_at": now}},
        return_document=ReturnDocument.AFTER,
    )
    if doc is None:
        return None

    await self._db["academy_memberships"].update_one(
        {"academy_id": academy_id, "user_id": canonical_user_id},
        {
            "$set": {
                "roles": list(roles),
                "status": "active",
                "updated_at": now,
            },
            "$setOnInsert": {
                "membership_id": str(new_ulid()),
                "academy_id": academy_id,
                "user_id": canonical_user_id,
                "invited_by": actor_id,
                "invited_at": now,
                "accepted_at": now,
                "created_at": now,
            },
        },
        upsert=True,
    )

    await self._write_audit(
        academy_id=academy_id,
        actor_id=actor_id,
        action="user.roles_changed",
        entity_id=canonical_user_id,
        reason=reason,
        changed_keys=["role", "roles"],
        before=before,
        after=doc,
    )
    return await self.get_admin_user(canonical_user_id, academy_id=academy_id)
```

Add helpers in the repo:

```python
def _primary_role(roles: tuple[Role, ...]) -> Role:
    for role in ("admin", "coach", "parent"):
        if role in roles:
            return role
    raise ValueError("at least one role is required")
```

Use existing linked student and session count logic from `get_admin_user()` instead of duplicating query shapes where practical.

**Step 5: Run tests**

Run:

```bash
cd backend
source .venv/bin/activate
pytest v2/tests/application/test_admin_user_edit.py -q
```

Expected: pass.

**Step 6: Commit**

```bash
git add backend/v2/contexts/identity/application/change_user_role_use_case.py \
        backend/v2/contexts/identity/application/use_cases/admin_directory.py \
        backend/v2/contexts/identity/infrastructure/mongo_user_repo.py \
        backend/v2/tests/application/test_admin_user_edit.py
git commit -m "Add admin multi-role identity use case"
```

---

### Task 2: Backend Admin BFF Route

**Files:**
- Modify: `backend/v2/interfaces/admin/views.py`
- Modify: `backend/v2/interfaces/admin/deps.py`
- Modify: `backend/v2/composition/admin.py`
- Modify: `backend/v2/interfaces/admin/directory_routes.py`
- Test: `backend/v2/tests/interface/test_admin_directory_routes.py`

**Step 1: Write failing interface tests**

Create or extend `backend/v2/tests/interface/test_admin_directory_routes.py`:

```python
def test_admin_can_patch_user_roles(admin_client):
    response = admin_client.patch(
        "/api/v2/admin/users/user-1/roles",
        json={
            "roles": ["parent", "coach"],
            "reason": "Coach also has enrolled child",
        },
    )

    assert response.status_code == 200
    body = response.json()
    assert body["role"] == "coach"
    assert body["roles"] == ["parent", "coach"]
```

Add a security regression:

```python
def test_parent_cannot_patch_user_roles(parent_client):
    response = parent_client.patch(
        "/api/v2/admin/users/user-1/roles",
        json={"roles": ["coach"], "reason": "bad"},
    )
    assert response.status_code == 404
```

**Step 2: Run tests to verify failure**

Run:

```bash
cd backend
source .venv/bin/activate
pytest v2/tests/interface/test_admin_directory_routes.py -q
```

Expected: route is missing or dependency not wired.

**Step 3: Add request model**

In `backend/v2/interfaces/admin/views.py`, add:

```python
class UpdateAdminUserRolesRequest(BaseModel):
    roles: list[Literal["admin", "coach", "parent"]] = Field(min_length=1)
    reason: str = Field(default="admin roles change", min_length=1, max_length=500)
```

Ensure `AdminUserView` includes `roles: list[...]` if it does not already. If changing `AdminUserView` is too broad, add `roles` only to `AdminUserDetailView` and return `AdminUserDetailView` from the new endpoint.

**Step 4: Wire dependency and composition**

Add `change_user_roles: ChangeUserRoles` to `AdminUseCases` in `backend/v2/interfaces/admin/deps.py`.

In `backend/v2/composition/admin.py`, instantiate:

```python
change_user_roles = ChangeUserRoles(users_r)
```

and include it in the returned `AdminUseCases`.

**Step 5: Add route**

In `backend/v2/interfaces/admin/directory_routes.py`, add:

```python
@router.patch("/users/{user_id}/roles", response_model=AdminUserDetailView)
async def update_user_roles(
    user_id: str,
    payload: UpdateAdminUserRolesRequest,
    claims: AuthClaims = Depends(require_persona("admin")),
    use_cases: AdminUseCases = Depends(get_admin_use_cases),
) -> AdminUserDetailView:
    if user_id == claims.user_id and "admin" not in payload.roles:
        raise SelfRoleChangeForbidden("cannot remove your own admin role")
    user = await use_cases.change_user_roles.execute(
        user_id,
        ChangeUserRolesCommand(
            roles=tuple(payload.roles),
            actor_id=claims.user_id,
            reason=payload.reason,
        ),
        academy_id=claims.academy_id,
    )
    return AdminUserDetailView(**user.model_dump())
```

Reuse or move the existing self-change exception so both old and new routes can use it.

**Step 6: Run route tests**

Run:

```bash
cd backend
source .venv/bin/activate
pytest v2/tests/interface/test_admin_directory_routes.py -q
```

Expected: pass.

**Step 7: Run focused backend tests**

Run:

```bash
cd backend
source .venv/bin/activate
pytest v2/tests/application/test_admin_user_edit.py v2/tests/interface/test_admin_directory_routes.py -q
```

Expected: pass.

**Step 8: Commit**

```bash
git add backend/v2/interfaces/admin/views.py \
        backend/v2/interfaces/admin/deps.py \
        backend/v2/composition/admin.py \
        backend/v2/interfaces/admin/directory_routes.py \
        backend/v2/tests/interface/test_admin_directory_routes.py
git commit -m "Expose admin multi-role user endpoint"
```

---

### Task 3: Frontend API Types and Admin Multi-Role Editor

**Files:**
- Modify: `frontend/lib/api/admin.ts`
- Modify: `frontend/components/admin/AdminUsersDirectory.tsx`
- Test: `frontend/lib/api/*.node-test.mjs` if adjacent API tests exist

**Step 1: Update frontend types**

In `frontend/lib/api/admin.ts`, change:

```ts
export interface AdminUserView {
  user_id: string;
  email: string;
  display_name: string;
  role: AdminUserRole;
  roles: AdminUserRole[];
  status: string;
  phone?: string | null;
}
```

Add:

```ts
export function updateAdminUserRoles(
  userId: string,
  roles: AdminUserRole[],
  reason = "Admin roles change",
): Promise<AdminUserDetail> {
  return apiFetch<AdminUserDetail>(`/admin/users/${encodeURIComponent(userId)}/roles`, {
    method: "PATCH",
    body: JSON.stringify({ roles, reason }),
  });
}
```

**Step 2: Replace single-role editing UI for existing users**

In `frontend/components/admin/AdminUsersDirectory.tsx`, add a role editor dialog for table rows:

- Trigger: compact button with role chips or an edit icon.
- Controls: three checkboxes/toggles for `Parent`, `Coach`, `Admin`.
- Required: at least one selected role.
- Reason input default: `Admin roles change`.
- Save calls `updateAdminUserRoles()`.
- On success, invalidate `queryKeys.admin.users(...)`.

Use stable checkbox controls, not a single select. Keep create-user flow as single-role for now unless widening create flow is trivial.

**Step 3: Display multiple role chips**

Update table role rendering:

```tsx
const displayRoles = user.roles?.length ? user.roles : [user.role];
```

Render one chip per role. Keep the primary `role` chip first by derived priority.

**Step 4: Keep filters working**

No filter UI change is required. `listAdminUsers("coach")` should return any user whose `roles` includes `coach` after backend filtering is preserved.

**Step 5: Run frontend checks**

Run:

```bash
cd frontend
pnpm typecheck
```

Expected: pass.

**Step 6: Commit**

```bash
git add frontend/lib/api/admin.ts frontend/components/admin/AdminUsersDirectory.tsx
git commit -m "Add admin multi-role user editor"
```

---

### Task 4: Multi-Role Persona Switching

**Files:**
- Modify: `frontend/app/(admin)/layout.tsx`
- Modify: `frontend/app/(coach)/layout.tsx`
- Modify: `frontend/app/(parent)/layout.tsx`
- Create or Modify: `frontend/components/persona/persona-switcher.tsx`
- Test: focused browser/manual verification

**Step 1: Add shared persona switcher component**

Create `frontend/components/persona/persona-switcher.tsx`:

```tsx
"use client";

import Link from "next/link";
import type { UserRole } from "@/lib/api/me";

const HOME_BY_ROLE: Record<UserRole, string> = {
  admin: "/admin",
  coach: "/coach/today",
  parent: "/parent/payments",
};

export function PersonaSwitcher({
  roles,
  currentRole,
}: {
  roles: UserRole[];
  currentRole: UserRole;
}) {
  if (roles.length <= 1) return null;

  return (
    <nav aria-label="Switch role" className="flex items-center gap-2">
      {roles.map((role) => (
        <Link
          key={role}
          href={HOME_BY_ROLE[role]}
          aria-current={role === currentRole ? "page" : undefined}
          className="rounded-md border px-2 py-1 text-xs font-medium"
        >
          {role[0].toUpperCase() + role.slice(1)}
        </Link>
      ))}
    </nav>
  );
}
```

Style it to match each layout; do not add marketing copy or explanatory text inside the app.

**Step 2: Mount in persona layouts**

In each persona layout, pass:

```tsx
<PersonaSwitcher roles={auth.user.roles} currentRole="coach" />
```

Use the existing authenticated `auth.user` from `usePersonaAuth()`.

**Step 3: Verify routing**

Manual browser checks:

1. Login as a user with `roles: ["parent", "coach"]`.
2. Confirm `/post-login` lands on `/coach/today`.
3. Confirm switcher shows `Coach` and `Parent`.
4. Click `Parent`; confirm `/parent/payments` loads.
5. Click `Coach`; confirm `/coach/today` loads.

**Step 4: Run frontend checks**

Run:

```bash
cd frontend
pnpm typecheck
pnpm lint
```

Expected: pass.

**Step 5: Commit**

```bash
git add frontend/components/persona/persona-switcher.tsx \
        'frontend/app/(admin)/layout.tsx' \
        'frontend/app/(coach)/layout.tsx' \
        'frontend/app/(parent)/layout.tsx'
git commit -m "Add persona switcher for multi-role users"
```

---

### Task 5: Data Consistency Repair and Operator Runbook

**Files:**
- Create: `scripts/prod/sync_user_roles_memberships.py`
- Create: `docs/runbooks/multi-role-users.md`
- Test: `backend/v2/tests/application/test_admin_user_edit.py` or a script unit test if script helpers are factored

**Step 1: Add a dry-run-first script**

Create `scripts/prod/sync_user_roles_memberships.py` that:

- Connects to Mongo using `MONGO_URL` and `DB_NAME`.
- Requires `--academy-id`.
- Defaults to dry-run.
- For each `users` row in the academy, reads `roles`.
- Upserts matching `academy_memberships.roles`.
- Optionally supports one targeted update:

```bash
python scripts/prod/sync_user_roles_memberships.py \
  --academy-id blno \
  --email kishoreraosubbarao@gmail.com \
  --roles parent,coach \
  --apply
```

Safety rules:

- Refuse `--apply` unless `--confirm-production` is passed when `APP_ENV=production`.
- Print before/after for each affected user.
- Never remove roles in bulk unless `--allow-role-removal` is explicitly passed.

**Step 2: Add runbook**

Create `docs/runbooks/multi-role-users.md` with:

- How roles work.
- Why session assignment is not app access.
- How to check `/me`.
- How to grant parent+coach via admin UI once available.
- Emergency data repair command.
- Rollback steps.

**Step 3: Verify script static behavior**

Run:

```bash
python scripts/prod/sync_user_roles_memberships.py --help
```

Expected: help text prints and exits 0.

**Step 4: Commit**

```bash
git add scripts/prod/sync_user_roles_memberships.py docs/runbooks/multi-role-users.md
git commit -m "Add multi-role user repair runbook"
```

---

### Task 6: End-to-End Verification

**Files:**
- Modify if practical: `frontend/e2e/specs/qa-defects.spec.ts`
- Update: `docs/test-results/active/<task-ledger>.md`

**Step 1: Add or update a focused E2E scenario**

Add a test scenario that seeds a user with:

```json
{
  "roles": ["parent", "coach"],
  "role": "coach"
}
```

Then verifies:

- Login reaches coach home.
- Parent route is accessible.
- Coach route is accessible.
- Admin coach selector includes the user.

**Step 2: Run focused checks**

Run:

```bash
scripts/local_test_stack.sh test
```

If E2E fixtures were touched, run:

```bash
cd frontend
pnpm e2e
```

**Step 3: Run pre-push checks**

Run:

```bash
scripts/dev/pre-push-checks.sh
```

Expected: pass.

**Step 4: Record verification**

Run:

```bash
scripts/dev/test_result.py verify admin-multi-role-users --message "pre-push checks passed"
```

**Step 5: Commit**

```bash
git add frontend/e2e/specs/qa-defects.spec.ts docs/test-results/active/<task-ledger>.md
git commit -m "Verify multi-role user workflows"
```

---

## Final Acceptance Criteria

- [ ] Admin can set a user to `["parent", "coach"]` from the UI.
- [ ] Backend persists both roles to `users.roles`.
- [ ] Backend derives `users.role = "coach"` for parent+coach users.
- [ ] Backend syncs `academy_memberships.roles`.
- [ ] `/api/v2/me` returns both roles after login.
- [ ] Parent+coach user lands on coach home by default.
- [ ] Parent+coach user can switch to parent surfaces.
- [ ] Coach session picker includes parent+coach users.
- [ ] Removing `parent` is blocked while linked students exist.
- [ ] Removing `coach` is blocked while active sessions exist.
- [ ] Audit log records role changes.
- [ ] Focused backend and frontend checks pass.

## Verification Commands

```bash
cd backend
source .venv/bin/activate
pytest v2/tests/application/test_admin_user_edit.py v2/tests/interface/test_admin_directory_routes.py -q
```

```bash
cd frontend
pnpm typecheck
pnpm lint
```

```bash
scripts/dev/pre-push-checks.sh
```

