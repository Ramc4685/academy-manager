# Multi-Persona View Switcher + Additive Role Management — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Let one user hold multiple personas (admin/coach/parent) with additive role management in the admin UI, and switch between persona views via a header switcher shown to multi-role users.

**Architecture:** Backend adds two small identity use cases (`AddUserRole`, `RemoveUserRole`) backed by new `MongoUserRepository` methods that update BOTH the legacy `users` doc and the SaaS source of truth `academy_memberships.roles` additively (the existing `change_role` clobbers roles). Frontend adds a `PersonaSwitcher` component (modeled on `TenantSwitcher`) mounted in the admin, coach, and parent shells, plus a `RolesPanel` on the admin user-detail page replacing the single-role `RoleChangePanel`.

**Tech Stack:** FastAPI + Motor/Mongo (backend/v2 DDD), Pydantic v2, pytest (asyncio_mode=auto, run from `backend/`), Next.js App Router + Tailwind v4 + React Query (frontend), Vitest for frontend unit logic.

## Global Constraints

- Coach/parent routes are NOT modified — they already authorize via `claims.roles` and scope by `claims.user_id`.
- `academy_memberships` is the SaaS role source of truth (claims are built from it); every role mutation must update it, mirroring to legacy `users.roles`/`role`.
- Role guard: a user must always keep ≥1 role; an admin may not remove their own `admin` role.
- Persona homes: admin → `/admin`, coach → `/coach/today`, parent → `/parent/payments` (must match `homeForRoles` in `frontend/lib/api/me.ts`).
- Wrong-persona admin routes return 404 (not 403) via `require_persona("admin")` — keep that convention.
- Backend tests run from `backend/`: `pytest v2/tests/...`. Frontend checks: `npm run typecheck && npm run lint` in `frontend/`.

---

### Task 1: `AddUserRole` / `RemoveUserRole` use cases

**Files:**
- Create: `backend/v2/contexts/identity/application/use_cases/manage_user_roles.py`
- Modify: `backend/v2/contexts/identity/application/errors.py` (add `CannotRemoveLastRole`)
- Test: `backend/v2/tests/application/identity/test_manage_user_roles.py`

**Interfaces:**
- Consumes: `AdminUserDetail` and `Role` from `backend.v2.contexts.identity.application.use_cases.admin_directory`; `UserNotFound` from `backend.v2.contexts.identity.application.errors`.
- Produces: `AddUserRole.execute(user_id: str, command: ModifyUserRoleCommand, *, academy_id: str) -> AdminUserDetail`, `RemoveUserRole.execute(...)` (same signature), `ModifyUserRoleCommand(role, actor_id, reason)`, port `AdminRoleModifier` with `add_role`/`remove_role`, error `CannotRemoveLastRole`. Task 2 implements the port; Task 3 wires the use cases.

- [ ] **Step 1: Write the failing tests**

Create `backend/v2/tests/application/identity/test_manage_user_roles.py`:

```python
from unittest.mock import AsyncMock

import pytest

from backend.v2.contexts.identity.application.errors import UserNotFound
from backend.v2.contexts.identity.application.use_cases.admin_directory import (
    AdminUserDetail,
)
from backend.v2.contexts.identity.application.use_cases.manage_user_roles import (
    AddUserRole,
    ModifyUserRoleCommand,
    RemoveUserRole,
)


def _detail(roles: list[str]) -> AdminUserDetail:
    return AdminUserDetail(
        user_id="user-1",
        email="user@example.com",
        display_name="User One",
        role=roles[0],
        status="active",
        phone=None,
        roles=roles,
        linked_student_count=0,
        session_count=0,
    )


@pytest.mark.asyncio
async def test_add_role_delegates_to_repo():
    repo = AsyncMock()
    repo.add_role.return_value = _detail(["admin", "coach"])

    result = await AddUserRole(repo).execute(
        "user-1",
        ModifyUserRoleCommand(role="coach", actor_id="admin-1", reason="Also coaches"),
        academy_id="acad",
    )

    assert set(result.roles) == {"admin", "coach"}
    repo.add_role.assert_awaited_once_with(
        "user-1", "coach", academy_id="acad", actor_id="admin-1", reason="Also coaches",
    )


@pytest.mark.asyncio
async def test_add_role_raises_when_user_not_found():
    repo = AsyncMock()
    repo.add_role.return_value = None
    with pytest.raises(UserNotFound):
        await AddUserRole(repo).execute(
            "user-x",
            ModifyUserRoleCommand(role="coach", actor_id="admin-1", reason="r"),
            academy_id="acad",
        )


@pytest.mark.asyncio
async def test_remove_role_delegates_to_repo():
    repo = AsyncMock()
    repo.remove_role.return_value = _detail(["admin"])

    result = await RemoveUserRole(repo).execute(
        "user-1",
        ModifyUserRoleCommand(role="coach", actor_id="admin-1", reason="No longer coaches"),
        academy_id="acad",
    )

    assert result.roles == ["admin"]
    repo.remove_role.assert_awaited_once_with(
        "user-1", "coach", academy_id="acad", actor_id="admin-1", reason="No longer coaches",
    )


@pytest.mark.asyncio
async def test_remove_role_raises_when_user_not_found():
    repo = AsyncMock()
    repo.remove_role.return_value = None
    with pytest.raises(UserNotFound):
        await RemoveUserRole(repo).execute(
            "user-x",
            ModifyUserRoleCommand(role="coach", actor_id="admin-1", reason="r"),
            academy_id="acad",
        )
```

- [ ] **Step 2: Run tests to verify they fail**

Run (from `backend/`): `pytest v2/tests/application/identity/test_manage_user_roles.py -v`
Expected: FAIL with `ModuleNotFoundError: ... manage_user_roles`

- [ ] **Step 3: Implement the use cases**

First, in `backend/v2/contexts/identity/application/errors.py`, add (mirroring the existing error classes' style — check how `UserNotFound` is declared there and match it):

```python
class CannotRemoveLastRole(Exception):
    """Raised when removing a role would leave the user with no roles."""
```

Create `backend/v2/contexts/identity/application/use_cases/manage_user_roles.py`:

```python
"""Additive role management for the admin directory.

Unlike ``ChangeUserRole`` (which replaces all roles with one), these use
cases add/remove a single role while preserving the rest, updating both
the legacy ``users`` doc and the ``academy_memberships`` source of truth.
"""

from typing import Protocol

from pydantic import BaseModel, Field

from backend.v2.contexts.identity.application.errors import UserNotFound
from backend.v2.contexts.identity.application.use_cases.admin_directory import (
    AdminUserDetail,
)
from backend.v2.contexts.identity.domain.models import Role


class ModifyUserRoleCommand(BaseModel):
    model_config = {"frozen": True}

    role: Role
    actor_id: str = Field(min_length=1)
    reason: str = Field(min_length=1, max_length=500)


class AdminRoleModifier(Protocol):
    async def add_role(
        self, user_id: str, role: Role, *, academy_id: str, actor_id: str, reason: str
    ) -> AdminUserDetail | None: ...

    async def remove_role(
        self, user_id: str, role: Role, *, academy_id: str, actor_id: str, reason: str
    ) -> AdminUserDetail | None: ...


class AddUserRole:
    def __init__(self, users: AdminRoleModifier) -> None:
        self._users = users

    async def execute(
        self, user_id: str, command: ModifyUserRoleCommand, *, academy_id: str
    ) -> AdminUserDetail:
        result = await self._users.add_role(
            user_id,
            command.role,
            academy_id=academy_id,
            actor_id=command.actor_id,
            reason=command.reason,
        )
        if result is None:
            raise UserNotFound(user_id)
        return result


class RemoveUserRole:
    def __init__(self, users: AdminRoleModifier) -> None:
        self._users = users

    async def execute(
        self, user_id: str, command: ModifyUserRoleCommand, *, academy_id: str
    ) -> AdminUserDetail:
        result = await self._users.remove_role(
            user_id,
            command.role,
            academy_id=academy_id,
            actor_id=command.actor_id,
            reason=command.reason,
        )
        if result is None:
            raise UserNotFound(user_id)
        return result
```

Note: verify `UserNotFound`'s constructor signature in `errors.py` (the existing `ChangeUserRole` raises it — copy its call style). If `AdminUserDetail`/`Role` live at slightly different import paths, use the same imports `admin_directory.py` itself uses.

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest v2/tests/application/identity/test_manage_user_roles.py -v`
Expected: 4 passed

- [ ] **Step 5: Commit**

```bash
git add backend/v2/contexts/identity/application/use_cases/manage_user_roles.py \
        backend/v2/contexts/identity/application/errors.py \
        backend/v2/tests/application/identity/test_manage_user_roles.py
git commit -m "feat(identity): additive AddUserRole/RemoveUserRole use cases"
```

---

### Task 2: Repository `add_role` / `remove_role` (users doc + academy_memberships)

**Files:**
- Modify: `backend/v2/contexts/identity/infrastructure/mongo_user_repo.py` (add two methods after `change_role`, ~line 492)

**Interfaces:**
- Consumes: existing helpers `self._id_filter`, `self._write_audit`, `self._to_domain`, `self.get_admin_user`.
- Produces: `MongoUserRepository.add_role(...)` / `.remove_role(...)` satisfying Task 1's `AdminRoleModifier` port. `remove_role` raises `CannotRemoveLastRole` when the user would end with zero roles.

- [ ] **Step 1: Implement both methods**

Add to `mongo_user_repo.py` (import `CannotRemoveLastRole` alongside the other application-error imports at the top of the file):

```python
    async def add_role(
        self,
        user_id: str,
        role: Role,
        *,
        academy_id: str,
        actor_id: str,
        reason: str,
    ) -> AdminUserDetail | None:
        return await self._modify_roles(
            user_id, role, adding=True,
            academy_id=academy_id, actor_id=actor_id, reason=reason,
        )

    async def remove_role(
        self,
        user_id: str,
        role: Role,
        *,
        academy_id: str,
        actor_id: str,
        reason: str,
    ) -> AdminUserDetail | None:
        return await self._modify_roles(
            user_id, role, adding=False,
            academy_id=academy_id, actor_id=actor_id, reason=reason,
        )

    async def _modify_roles(
        self,
        user_id: str,
        role: Role,
        *,
        adding: bool,
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

        current = list(before.get("roles") or ([before["role"]] if before.get("role") else []))
        if adding:
            new_roles = current if role in current else [*current, role]
        else:
            new_roles = [r for r in current if r != role]
            if not new_roles:
                raise CannotRemoveLastRole(user_id)
        # Keep the legacy single `role` field meaningful: preserve it unless
        # it was the role being removed, in which case fall back to the first
        # remaining role.
        primary = before.get("role")
        if primary not in new_roles:
            primary = new_roles[0]

        doc = await self.collection.find_one_and_update(
            {"academy_id": academy_id, **self._id_filter(user_id)},
            {"$set": {"role": primary, "roles": new_roles, "updated_at": now}},
            return_document=ReturnDocument.AFTER,
        )
        if doc is None:
            return None

        resolved_user_id = self._to_domain(doc).user_id
        # Mirror into the SaaS source of truth (claims are built from this).
        membership_update: dict[str, Any] = (
            {"$addToSet": {"roles": role}} if adding else {"$pull": {"roles": role}}
        )
        membership_update["$set"] = {"updated_at": now}
        await self._db["academy_memberships"].update_one(
            {"academy_id": academy_id, "user_id": resolved_user_id},
            membership_update,
        )

        await self._write_audit(
            academy_id=academy_id,
            actor_id=actor_id,
            action="user.role_added" if adding else "user.role_removed",
            entity_id=resolved_user_id,
            reason=reason,
            changed_keys=["role", "roles"],
            before=before,
            after=doc,
        )
        return await self.get_admin_user(resolved_user_id, academy_id=academy_id)
```

Notes for the implementer:
- `Role`, `AdminUserDetail`, `datetime`, `UTC`, `ReturnDocument`, `Any` are already imported in this file (verify; add any missing import).
- Match `_write_audit`'s exact keyword signature as used by `change_role` (lines 461–492).
- Do NOT touch `change_role` — the existing single-role PATCH `/admin/users/{id}/role` keeps its replace semantics for backward compatibility; the new endpoints are additive.

- [ ] **Step 2: Sanity-run the identity test suites (no regressions)**

Run: `pytest v2/tests/application/identity/ v2/tests/application/test_admin_user_edit.py -v`
Expected: all pass

- [ ] **Step 3: Commit**

```bash
git add backend/v2/contexts/identity/infrastructure/mongo_user_repo.py
git commit -m "feat(identity): additive role writes to users doc and academy_memberships"
```

---

### Task 3: Admin routes, views, wiring, interface tests

**Files:**
- Modify: `backend/v2/interfaces/admin/directory_routes.py` (new routes after `bulk_invite_parents`, ~line 153)
- Modify: `backend/v2/interfaces/admin/views.py` (add `ModifyUserRoleRequest`, ~line 212)
- Modify: `backend/v2/interfaces/admin/deps.py` (add fields to `AdminUseCases`, ~line 229)
- Modify: `backend/v2/composition/admin.py` (instantiate + assign, near `create_admin_user` wiring at lines ~3361 and ~5677)
- Modify: `backend/v2/tests/interface/conftest.py` (fake role modifier in `_build_admin_use_cases`, ~line 1560)
- Test: `backend/v2/tests/interface/test_admin_directory.py`

**Interfaces:**
- Consumes: Task 1's `AddUserRole`/`RemoveUserRole`/`ModifyUserRoleCommand`/`CannotRemoveLastRole`.
- Produces: `POST /api/v2/admin/users/{user_id}/roles` (body `{role, reason}`) → 200 `AdminUserDetailView`; `DELETE /api/v2/admin/users/{user_id}/roles/{role}?reason=...` → 200 `AdminUserDetailView`; 409 on self-admin-removal and last-role-removal. Task 4's frontend calls these.

- [ ] **Step 1: Write the failing interface tests**

Append to `backend/v2/tests/interface/test_admin_directory.py`:

```python
def test_admin_adds_role_to_user(admin_client):
    r = admin_client.post(
        "/api/v2/admin/users/coach-1/roles",
        json={"role": "parent", "reason": "Coach is also a parent"},
    )
    assert r.status_code == 200, r.text
    assert set(r.json()["roles"]) == {"coach", "parent"}


def test_admin_removes_role_from_user(admin_client):
    admin_client.post(
        "/api/v2/admin/users/coach-1/roles",
        json={"role": "parent", "reason": "setup"},
    )
    r = admin_client.delete(
        "/api/v2/admin/users/coach-1/roles/parent?reason=No%20longer%20a%20parent"
    )
    assert r.status_code == 200, r.text
    assert r.json()["roles"] == ["coach"]


def test_admin_cannot_remove_own_admin_role(admin_client):
    # admin_client's claims user_id — check conftest _claims(): f"u-admin"
    r = admin_client.delete("/api/v2/admin/users/u-admin/roles/admin?reason=x")
    assert r.status_code == 409


def test_cannot_remove_last_role(admin_client):
    r = admin_client.delete("/api/v2/admin/users/coach-1/roles/coach?reason=x")
    assert r.status_code == 409


def test_role_endpoints_wrong_persona_404(coach_on_admin_client):
    assert (
        coach_on_admin_client.post(
            "/api/v2/admin/users/coach-1/roles", json={"role": "parent", "reason": "x"}
        ).status_code
        == 404
    )
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest v2/tests/interface/test_admin_directory.py -v`
Expected: new tests FAIL (405/404 — routes don't exist)

- [ ] **Step 3: Implement views, routes, deps, composition, and conftest fake**

In `backend/v2/interfaces/admin/views.py` add:

```python
class ModifyUserRoleRequest(BaseModel):
    role: Literal["admin", "coach", "parent"]
    reason: str = Field(default="Admin role change", min_length=1, max_length=500)
```

In `backend/v2/interfaces/admin/deps.py`, add to the `AdminUseCases` dataclass (next to `create_admin_user`, ~line 229):

```python
    add_user_role: AddUserRole | None = None
    remove_user_role: RemoveUserRole | None = None
```

(import `AddUserRole`, `RemoveUserRole` from `backend.v2.contexts.identity.application.use_cases.manage_user_roles`; follow the file's existing import grouping. If the dataclass has non-default fields after this position, keep the `= None` defaults and place accordingly.)

In `backend/v2/interfaces/admin/directory_routes.py` add:

```python
@router.post("/users/{user_id}/roles", response_model=AdminUserDetailView)
async def add_user_role(
    user_id: str,
    payload: ModifyUserRoleRequest,
    claims: AuthClaims = Depends(require_persona("admin")),
    use_cases: AdminUseCases = Depends(get_admin_use_cases),
) -> AdminUserDetailView:
    use_case = use_cases.add_user_role
    if use_case is None:
        raise HTTPException(status_code=503, detail="Role management is not configured")
    user = await use_case.execute(
        user_id,
        ModifyUserRoleCommand(
            role=payload.role, actor_id=claims.user_id, reason=payload.reason
        ),
        academy_id=claims.academy_id,
    )
    return AdminUserDetailView(**user.model_dump())


@router.delete("/users/{user_id}/roles/{role}", response_model=AdminUserDetailView)
async def remove_user_role(
    user_id: str,
    role: Literal["admin", "coach", "parent"],
    reason: str = Query(default="Admin role change", min_length=1, max_length=500),
    claims: AuthClaims = Depends(require_persona("admin")),
    use_cases: AdminUseCases = Depends(get_admin_use_cases),
) -> AdminUserDetailView:
    if claims.user_id == user_id and role == "admin":
        raise HTTPException(
            status_code=409, detail="You cannot remove your own admin role"
        )
    use_case = use_cases.remove_user_role
    if use_case is None:
        raise HTTPException(status_code=503, detail="Role management is not configured")
    try:
        user = await use_case.execute(
            user_id,
            ModifyUserRoleCommand(role=role, actor_id=claims.user_id, reason=reason),
            academy_id=claims.academy_id,
        )
    except CannotRemoveLastRole:
        raise HTTPException(
            status_code=409, detail="User must keep at least one role"
        ) from None
    return AdminUserDetailView(**user.model_dump())
```

(Imports: `ModifyUserRoleRequest` from views; `ModifyUserRoleCommand`, `CannotRemoveLastRole`, `AddUserRole`… from the identity use case/error modules; `Query` from fastapi — match existing import style in the file.)

In `backend/v2/composition/admin.py`, next to `create_admin_user = CreateAdminUser(users_r)` (~line 3361):

```python
    add_user_role = AddUserRole(users_r)
    remove_user_role = RemoveUserRole(users_r)
```

and in the `AdminUseCases(...)` construction (~line 5677): `add_user_role=add_user_role, remove_user_role=remove_user_role,`.

In `backend/v2/tests/interface/conftest.py`, add a fake implementing `AdminRoleModifier` and wire it into `_build_admin_use_cases`. It should keep an in-memory roles dict seeded to match the existing directory fakes (`coach-1` → `["coach"]`, `u-admin` → `["admin"]`):

```python
class _FakeRoleModifier:
    def __init__(self) -> None:
        self.roles: dict[str, list[str]] = {
            "coach-1": ["coach"],
            "u-admin": ["admin"],
        }

    def _detail(self, user_id: str) -> AdminUserDetail:
        roles = self.roles[user_id]
        return AdminUserDetail(
            user_id=user_id,
            email=f"{user_id}@example.com",
            display_name=user_id,
            role=roles[0],
            status="active",
            phone=None,
            roles=roles,
            linked_student_count=0,
            session_count=0,
        )

    async def add_role(self, user_id, role, *, academy_id, actor_id, reason):
        if user_id not in self.roles:
            return None
        if role not in self.roles[user_id]:
            self.roles[user_id].append(role)
        return self._detail(user_id)

    async def remove_role(self, user_id, role, *, academy_id, actor_id, reason):
        from backend.v2.contexts.identity.application.errors import CannotRemoveLastRole

        if user_id not in self.roles:
            return None
        remaining = [r for r in self.roles[user_id] if r != role]
        if not remaining:
            raise CannotRemoveLastRole(user_id)
        self.roles[user_id] = remaining
        return self._detail(user_id)
```

Wire in `_build_admin_use_cases`: `_role_modifier = _FakeRoleModifier()`, then `add_user_role=AddUserRole(_role_modifier), remove_user_role=RemoveUserRole(_role_modifier),` in the `AdminUseCases(...)` call.

Note: `UserNotFound` → HTTP status mapping already exists via `register_exception_handlers` (the existing role PATCH route relies on it). Confirm what status `UserNotFound` maps to; no new handler needed. Prefer the localized try/except for `CannotRemoveLastRole` as written.

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest v2/tests/interface/test_admin_directory.py v2/tests/application/identity/ -v`
Expected: all pass (adjust the self-admin test's user id to match `_claims("admin").user_id` from conftest if it isn't `u-admin`)

- [ ] **Step 5: Run the full backend gate**

Run: `cd backend && ruff format --check . && ruff check . && pytest v2/tests -q`
Expected: clean; fix formatting if flagged.

- [ ] **Step 6: Commit**

```bash
git add backend/v2/interfaces/admin backend/v2/composition/admin.py backend/v2/tests/interface
git commit -m "feat(admin): add/remove role endpoints with self-lockout and last-role guards"
```

---

### Task 4: Frontend API functions + `PersonaSwitcher` component + shell mounts

**Files:**
- Modify: `frontend/lib/api/admin.ts` (~line 1369, after `updateAdminUserRole`)
- Create: `frontend/components/persona/persona-switcher.tsx`
- Modify: `frontend/app/(admin)/layout.tsx` (header action cluster, ~line 390)
- Modify: `frontend/app/(coach)/layout.tsx` (header action cluster, ~line 54)
- Modify: `frontend/app/(parent)/layout.tsx` (header action cluster, ~line 52)

**Interfaces:**
- Consumes: `getCurrentUser`, `UserRole` from `@/lib/api/me`; `apiFetch` from `@/lib/api/client`; `AdminUserDetail` type from `@/lib/api/admin`.
- Produces: `addAdminUserRole(userId, role, reason)` / `removeAdminUserRole(userId, role, reason)` (used by Task 5), `<PersonaSwitcher current="admin" | "coach" | "parent" variant?="dark" />`.

- [ ] **Step 1: Add API functions**

In `frontend/lib/api/admin.ts` after `updateAdminUserRole`:

```ts
export function addAdminUserRole(
  userId: string,
  role: AdminUserRole,
  reason = "Admin role change",
): Promise<AdminUserDetail> {
  return apiFetch<AdminUserDetail>(
    `/admin/users/${encodeURIComponent(userId)}/roles`,
    { method: "POST", body: JSON.stringify({ role, reason }) },
  );
}

export function removeAdminUserRole(
  userId: string,
  role: AdminUserRole,
  reason = "Admin role change",
): Promise<AdminUserDetail> {
  return apiFetch<AdminUserDetail>(
    `/admin/users/${encodeURIComponent(userId)}/roles/${role}?reason=${encodeURIComponent(reason)}`,
    { method: "DELETE" },
  );
}
```

- [ ] **Step 2: Create the `PersonaSwitcher` component**

Create `frontend/components/persona/persona-switcher.tsx` (pattern copied from `TenantSwitcher`: hand-rolled listbox, outside-click + Escape close, `data-testid` conventions):

```tsx
"use client";

/**
 * Persona (view) switcher.
 *
 * Shown only when the current user holds two or more roles. Lists the
 * personas the user holds and navigates to that persona's home route.
 * General across all role combinations (admin/coach/parent).
 */

import { useEffect, useRef, useState } from "react";
import { useRouter } from "next/navigation";
import { useQuery } from "@tanstack/react-query";

import { getCurrentUser, type UserRole } from "@/lib/api/me";

const PERSONA_HOME: Record<UserRole, string> = {
  admin: "/admin",
  coach: "/coach/today",
  parent: "/parent/payments",
};

const PERSONA_LABEL: Record<UserRole, string> = {
  admin: "Admin view",
  coach: "Coach view",
  parent: "Parent view",
};

const PERSONA_ORDER: UserRole[] = ["admin", "coach", "parent"];

export function PersonaSwitcher({
  current,
  variant = "light",
}: {
  current: UserRole;
  variant?: "light" | "dark";
}) {
  const router = useRouter();
  const [open, setOpen] = useState(false);
  const containerRef = useRef<HTMLDivElement | null>(null);
  const meQuery = useQuery({ queryKey: ["me", "persona-switcher"], queryFn: getCurrentUser });

  useEffect(() => {
    if (!open) return;
    const onDocClick = (e: MouseEvent) => {
      if (containerRef.current && !containerRef.current.contains(e.target as Node)) {
        setOpen(false);
      }
    };
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") setOpen(false);
    };
    document.addEventListener("mousedown", onDocClick);
    document.addEventListener("keydown", onKey);
    return () => {
      document.removeEventListener("mousedown", onDocClick);
      document.removeEventListener("keydown", onKey);
    };
  }, [open]);

  const roles = PERSONA_ORDER.filter((r) => meQuery.data?.roles.includes(r));
  if (roles.length < 2) return null;

  const buttonClasses =
    variant === "dark"
      ? "text-[12px] font-semibold rounded-md border border-white/20 bg-white/10 px-2.5 py-1 text-white hover:bg-white/20 focus:outline-none focus:ring-2 focus:ring-white/40 inline-flex items-center gap-1.5"
      : "text-[12px] font-semibold rounded-md border border-rally-line bg-white px-2.5 py-1 text-rally-ink hover:bg-neutral-50 focus:outline-none focus:ring-2 focus:ring-rally-cobalt-600 inline-flex items-center gap-1.5";

  return (
    <div ref={containerRef} className="relative">
      <button
        type="button"
        data-testid="persona-switcher-button"
        aria-haspopup="listbox"
        aria-expanded={open}
        aria-label="Switch view"
        onClick={() => setOpen((v) => !v)}
        className={buttonClasses}
      >
        <span>{PERSONA_LABEL[current]}</span>
        <span aria-hidden="true">{open ? "▴" : "▾"}</span>
      </button>
      {open && (
        <ul
          role="listbox"
          aria-label="Available views"
          data-testid="persona-switcher-menu"
          className="absolute right-0 mt-1 w-44 rounded-md border border-rally-line bg-white shadow-lg z-40 py-1"
        >
          {roles.map((role) => (
            <li key={role}>
              <button
                type="button"
                role="option"
                aria-selected={role === current}
                data-testid={`persona-switcher-option-${role}`}
                onClick={() => {
                  setOpen(false);
                  if (role !== current) router.push(PERSONA_HOME[role]);
                }}
                className={`w-full px-3 py-2 text-left text-[13px] hover:bg-neutral-50 ${
                  role === current ? "font-semibold text-rally-ink" : "text-slate-600"
                }`}
              >
                {PERSONA_LABEL[role]}
              </button>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}
```

- [ ] **Step 3: Mount in the three shells**

`frontend/app/(admin)/layout.tsx` — in the header action cluster (line ~390), before `<TenantSwitcher />`:

```tsx
          <PersonaSwitcher current="admin" />
          <TenantSwitcher />
```

with import `import { PersonaSwitcher } from "@/components/persona/persona-switcher";`.

`frontend/app/(coach)/layout.tsx` — in the right-side header cluster (`<div className="flex items-center gap-2">`, before the Offline pill):

```tsx
          <PersonaSwitcher current="coach" variant="dark" />
```

`frontend/app/(parent)/layout.tsx` — same position in its header action cluster:

```tsx
          <PersonaSwitcher current="parent" variant="dark" />
```

- [ ] **Step 4: Typecheck + lint**

Run: `cd frontend && npm run typecheck && npm run lint`
Expected: clean

- [ ] **Step 5: Commit**

```bash
git add frontend/lib/api/admin.ts frontend/components/persona/persona-switcher.tsx \
        "frontend/app/(admin)/layout.tsx" "frontend/app/(coach)/layout.tsx" "frontend/app/(parent)/layout.tsx"
git commit -m "feat(frontend): persona view switcher for multi-role users"
```

---

### Task 5: `RolesPanel` on admin user detail (additive role UI)

**Files:**
- Modify: `frontend/app/(admin)/admin/users/[userId]/page.tsx` (replace `RoleChangePanel`, lines ~609–709, and its usage ~lines 79–96)

**Interfaces:**
- Consumes: `addAdminUserRole` / `removeAdminUserRole` from Task 4; `AdminUserDetail.roles`; existing `MutationMessages` component and `academyRoles` constant in the same file.
- Produces: `RolesPanel` — checkbox per role, reason input, Save applies the diff via sequential add/remove calls.

- [ ] **Step 1: Replace `RoleChangePanel` with `RolesPanel`**

In `frontend/app/(admin)/admin/users/[userId]/page.tsx`, replace the `RoleChangePanel` function with:

```tsx
function RolesPanel({
  user,
  onSaved,
}: {
  user: AdminUserDetail;
  onSaved: () => void;
}) {
  const initialRoles = user.roles.length > 0 ? user.roles : [user.role];
  const [selected, setSelected] = useState<AdminUserRole[]>(initialRoles);
  const [reason, setReason] = useState("Admin role change");
  const [submitError, setSubmitError] = useState<string | null>(null);
  const [submitOk, setSubmitOk] = useState(false);

  useEffect(() => {
    setSelected(user.roles.length > 0 ? user.roles : [user.role]);
  }, [user.roles, user.role]);

  const mutation = useMutation({
    mutationFn: async () => {
      const current = new Set(initialRoles);
      const next = new Set(selected);
      for (const role of academyRoles) {
        if (next.has(role) && !current.has(role)) {
          await addAdminUserRole(user.user_id, role, reason);
        }
      }
      for (const role of academyRoles) {
        if (current.has(role) && !next.has(role)) {
          await removeAdminUserRole(user.user_id, role, reason);
        }
      }
    },
    onSuccess: () => {
      setSubmitError(null);
      setSubmitOk(true);
      onSaved();
    },
    onError: (err: unknown) => {
      setSubmitOk(false);
      setSubmitError(err instanceof Error ? err.message : "Could not update roles.");
    },
  });

  const toggle = (role: AdminUserRole) => {
    setSubmitOk(false);
    setSelected((prev) =>
      prev.includes(role) ? prev.filter((r) => r !== role) : [...prev, role],
    );
  };

  return (
    <form
      className="space-y-3 rounded-lg border border-rally-line bg-white p-4"
      onSubmit={(e) => {
        e.preventDefault();
        if (selected.length === 0) {
          setSubmitError("User must keep at least one role.");
          return;
        }
        mutation.mutate();
      }}
    >
      <h2 className="text-sm font-semibold text-rally-ink">Roles</h2>
      <p className="text-xs text-slate-500">
        A user can hold multiple roles — e.g. an admin who also coaches, or a
        coach who is also a parent. Users with more than one role get a view
        switcher in the app header.
      </p>
      <div className="flex flex-wrap gap-3">
        {academyRoles.map((role) => (
          <label key={role} className="inline-flex items-center gap-2 text-sm">
            <input
              type="checkbox"
              checked={selected.includes(role)}
              onChange={() => toggle(role)}
              data-testid={`role-checkbox-${role}`}
            />
            <span className="capitalize">{role}</span>
          </label>
        ))}
      </div>
      <label className="block text-sm">
        <span className="text-slate-600">Reason</span>
        <input
          value={reason}
          onChange={(e) => setReason(e.target.value)}
          required
          className="mt-1 w-full rounded-md border border-rally-line px-2 py-1.5 text-sm"
        />
      </label>
      <MutationMessages error={submitError} ok={submitOk} />
      <Button type="submit" size="sm" disabled={mutation.isPending}>
        {mutation.isPending ? "Saving…" : "Save roles"}
      </Button>
    </form>
  );
}
```

Update the page composition to render `<RolesPanel user={...} onSaved={...} />` where `<RoleChangePanel ...>` was, update imports (`addAdminUserRole`, `removeAdminUserRole` from `@/lib/api/admin`), and delete the now-unused `updateAdminUserRole` import if nothing else uses it. Match the page's existing `Button`/section wrapper classes — if surrounding panels use different classes, copy those instead.

- [ ] **Step 2: Typecheck + lint**

Run: `cd frontend && npm run typecheck && npm run lint`
Expected: clean

- [ ] **Step 3: Commit**

```bash
git add "frontend/app/(admin)/admin/users/[userId]/page.tsx"
git commit -m "feat(admin-ui): additive roles panel replaces single-role change"
```

---

### Task 6: Full verification

- [ ] **Step 1: Backend full suite**

Run: `cd backend && ruff format --check . && ruff check . && pytest v2/tests -q`
Expected: clean. Also run the repo's import-contract check if part of the pre-push suite (mirror the 7-check pipeline).

- [ ] **Step 2: Frontend checks**

Run: `cd frontend && npm run typecheck && npm run lint`
Expected: clean

- [ ] **Step 3: Manual/e2e smoke (staging or local stack)**

1. As admin, open `/admin/users/<own user id>`, add the `coach` role.
2. Reload — header shows the persona switcher; switch to Coach view → lands on `/coach/today`.
3. Assign self to a session (existing coach picker uses `GET /admin/users?role=coach`, which now includes the admin) and mark attendance.
4. Switch back to Admin view.
5. Verify a single-role user sees no switcher.
6. Verify removing own admin role is rejected (409 surfaced as inline error).

- [ ] **Step 4: Release notes + commit**

Add `docs/release-notes/2026-07-09-feat-persona-switcher.md` following the existing release-note format in `docs/release-notes/`, commit.
