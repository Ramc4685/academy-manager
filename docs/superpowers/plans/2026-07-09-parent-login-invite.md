# Non-Google Parent Login (Admin-Created Accounts + Set-Password Invite) — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Parents without Google accounts (Yahoo/Hotmail/etc.) get a login: the admin creates their account (email already on file), the system emails a branded Firebase "set your password" link via Resend, and the parent logs in with email + password to view kids and pay.

**Architecture:** A new identity use case `SendLoginInvite` composes three ports: a Firebase password-reset-link generator (net-new method on `FirebaseAdminAdapter`), the existing communications `EmailSendPort` (Resend in prod / Stub in dev, same env-gating as digests), and an invite-state recorder on `MongoUserRepository`. The admin `create_user` and `bulk_invite_parents` routes auto-send the invite best-effort after provisioning; a new `POST /admin/users/{id}/login-invite` route re-sends. Frontend adds an "Add user" page and an invite button/indicator on the user detail page.

**Tech Stack:** FastAPI + Motor/Mongo, firebase-admin (`generate_password_reset_link`), Resend via existing `ResendEmailSendPort`, Pydantic v2, pytest from `backend/`; Next.js + React Query + Tailwind v4 frontend.

## Global Constraints

- Email/password login already works (`frontend/lib/auth/firebase.ts` `signInWithEmail`); backend blocks unverified password-provider emails (`_require_verified_password_provider_email` in `load_auth_claims.py`). Completing a Firebase password reset marks the email verified, so the invite flow satisfies this — do not weaken the verification check.
- Never email a literal one-time password; only the Firebase reset link.
- Invite send failures must NOT fail user creation — log and surface `login_invite_sent_at: null` so the admin can re-send.
- Email sending must use the existing env-gated pattern: `ResendEmailSendPort` when `settings.email_delivery_enabled and settings.resend_api_key`, else `StubEmailSendPort` (see `backend/v2/composition/digests.py:204-241` and `_email_sender` in `composition/admin.py:2817-2825` — reuse `_email_sender` if it's in scope where you wire this).
- All datetimes stored as timezone-aware UTC (`datetime.now(UTC)`), consistent with the rest of `mongo_user_repo.py`.
- Backend tests run from `backend/`: `pytest v2/tests/...`. Frontend: `npm run typecheck && npm run lint`.

---

### Task 1: `SendLoginInvite` use case

**Files:**
- Create: `backend/v2/contexts/identity/application/use_cases/send_login_invite.py`
- Modify: `backend/v2/contexts/identity/application/errors.py` (add `LoginInviteSendFailed`)
- Test: `backend/v2/tests/application/identity/test_send_login_invite.py`

**Interfaces:**
- Consumes: `AdminUserDetail` from `admin_directory.py`; `ResolvedRecipient`, `SendOutcome`, `EmailSendPort` from `backend.v2.contexts.communications.application.ports`; `UserNotFound` from identity errors.
- Produces: `SendLoginInvite.execute(user_id: str, *, academy_id: str) -> LoginInviteResult` where `LoginInviteResult(sent_at: datetime)`; ports `PasswordResetLinkPort.generate_password_reset_link(email) -> str`, `LoginInviteRecorder.record_login_invite(user_id, *, academy_id, sent_at) -> None`, `AcademyNameLookup.get_academy_name(academy_id) -> str | None`; error `LoginInviteSendFailed`. Tasks 2–3 implement and wire these.

- [ ] **Step 1: Write the failing tests**

Create `backend/v2/tests/application/identity/test_send_login_invite.py`:

```python
from unittest.mock import AsyncMock

import pytest

from backend.v2.contexts.communications.application.ports import SendOutcome
from backend.v2.contexts.identity.application.errors import (
    LoginInviteSendFailed,
    UserNotFound,
)
from backend.v2.contexts.identity.application.use_cases.admin_directory import (
    AdminUserDetail,
)
from backend.v2.contexts.identity.application.use_cases.send_login_invite import (
    SendLoginInvite,
)


def _user() -> AdminUserDetail:
    return AdminUserDetail(
        user_id="parent-1",
        email="parent@yahoo.com",
        display_name="Pat Parent",
        role="parent",
        status="active",
        phone=None,
        roles=["parent"],
        linked_student_count=1,
        session_count=0,
    )


def _use_case(users, links=None, sender=None, academies=None):
    links = links or AsyncMock()
    links.generate_password_reset_link.return_value = "https://reset.example/link"
    sender = sender or AsyncMock()
    sender.send.return_value = SendOutcome(
        ok=True, provider_message_id="msg-1", failed_reason=None
    )
    academies = academies or AsyncMock()
    academies.get_academy_name.return_value = "Smash Academy"
    return SendLoginInvite(users=users, links=links, sender=sender, academies=academies), links, sender


@pytest.mark.asyncio
async def test_sends_branded_set_password_email_and_records_invite():
    users = AsyncMock()
    users.get_admin_user.return_value = _user()
    use_case, links, sender = _use_case(users)

    result = await use_case.execute("parent-1", academy_id="acad")

    links.generate_password_reset_link.assert_awaited_once_with("parent@yahoo.com")
    sender.send.assert_awaited_once()
    kwargs = sender.send.await_args.kwargs
    assert kwargs["recipient"].email == "parent@yahoo.com"
    assert "Smash Academy" in kwargs["subject"]
    assert "https://reset.example/link" in kwargs["body"]
    users.record_login_invite.assert_awaited_once()
    assert result.sent_at is not None


@pytest.mark.asyncio
async def test_falls_back_to_generic_academy_name():
    users = AsyncMock()
    users.get_admin_user.return_value = _user()
    academies = AsyncMock()
    academies.get_academy_name.return_value = None
    use_case, _, sender = _use_case(users, academies=academies)

    await use_case.execute("parent-1", academy_id="acad")

    assert "your academy" in sender.send.await_args.kwargs["subject"]


@pytest.mark.asyncio
async def test_raises_when_user_not_found():
    users = AsyncMock()
    users.get_admin_user.return_value = None
    use_case, _, _ = _use_case(users)
    with pytest.raises(UserNotFound):
        await use_case.execute("missing", academy_id="acad")


@pytest.mark.asyncio
async def test_raises_and_does_not_record_when_send_fails():
    users = AsyncMock()
    users.get_admin_user.return_value = _user()
    sender = AsyncMock()
    sender.send.return_value = SendOutcome(
        ok=False, provider_message_id=None, failed_reason="boom"
    )
    use_case, _, _ = _use_case(users, sender=sender)

    with pytest.raises(LoginInviteSendFailed):
        await use_case.execute("parent-1", academy_id="acad")
    users.record_login_invite.assert_not_awaited()
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest v2/tests/application/identity/test_send_login_invite.py -v`
Expected: FAIL with `ModuleNotFoundError: ... send_login_invite`

- [ ] **Step 3: Implement the use case**

In `backend/v2/contexts/identity/application/errors.py` add:

```python
class LoginInviteSendFailed(Exception):
    """Raised when the set-password invite email could not be sent."""
```

Create `backend/v2/contexts/identity/application/use_cases/send_login_invite.py`:

```python
"""Send a 'set your password' login invite to an admin-created user.

Used for parents (and others) who do not use Google sign-in: the admin
provisions the Firebase account, then this use case emails a Firebase
password-reset link so the user chooses their own password. Completing
the link also marks the Firebase email verified, which the password
login path requires.
"""

from datetime import UTC, datetime
from typing import Protocol

from pydantic import BaseModel

from backend.v2.contexts.communications.application.ports import (
    EmailSendPort,
    ResolvedRecipient,
)
from backend.v2.contexts.identity.application.errors import (
    LoginInviteSendFailed,
    UserNotFound,
)
from backend.v2.contexts.identity.application.use_cases.admin_directory import (
    AdminUserDetail,
)


class PasswordResetLinkPort(Protocol):
    async def generate_password_reset_link(self, email: str) -> str: ...


class LoginInviteRecorder(Protocol):
    async def get_admin_user(
        self, user_id: str, academy_id: str
    ) -> AdminUserDetail | None: ...

    async def record_login_invite(
        self, user_id: str, *, academy_id: str, sent_at: datetime
    ) -> None: ...


class AcademyNameLookup(Protocol):
    async def get_academy_name(self, academy_id: str) -> str | None: ...


class LoginInviteResult(BaseModel):
    model_config = {"frozen": True}

    sent_at: datetime


def _invite_body(*, display_name: str, academy_name: str, reset_link: str) -> str:
    return f"""
<div style="font-family: -apple-system, 'Segoe UI', sans-serif; max-width: 520px; margin: 0 auto;">
  <h2 style="color: #0a0f1c;">Your {academy_name} account is ready</h2>
  <p>Hi {display_name},</p>
  <p>Your account at <strong>{academy_name}</strong> has been set up. Set your
  password to log in, see your children's enrollment, and make payments.</p>
  <p style="margin: 24px 0;">
    <a href="{reset_link}"
       style="background: #2545d3; color: #ffffff; padding: 12px 20px;
              border-radius: 8px; text-decoration: none; font-weight: 600;">
      Set your password
    </a>
  </p>
  <p style="color: #64748b; font-size: 13px;">This link expires after a short
  time. If it has expired, ask your academy to send a new one, or use
  &ldquo;Forgot password&rdquo; on the login page with this email address.</p>
</div>
"""


class SendLoginInvite:
    def __init__(
        self,
        *,
        users: LoginInviteRecorder,
        links: PasswordResetLinkPort,
        sender: EmailSendPort,
        academies: AcademyNameLookup,
    ) -> None:
        self._users = users
        self._links = links
        self._sender = sender
        self._academies = academies

    async def execute(self, user_id: str, *, academy_id: str) -> LoginInviteResult:
        user = await self._users.get_admin_user(user_id, academy_id=academy_id)
        if user is None:
            raise UserNotFound(user_id)

        reset_link = await self._links.generate_password_reset_link(str(user.email))
        academy_name = await self._academies.get_academy_name(academy_id) or "your academy"

        outcome = await self._sender.send(
            recipient=ResolvedRecipient(
                user_id=user.user_id,
                email=str(user.email),
                display_name=user.display_name,
            ),
            subject=f"Set your password for {academy_name}",
            body=_invite_body(
                display_name=user.display_name,
                academy_name=academy_name,
                reset_link=reset_link,
            ),
        )
        if not outcome.ok:
            raise LoginInviteSendFailed(outcome.failed_reason or "send failed")

        sent_at = datetime.now(UTC)
        await self._users.record_login_invite(
            user.user_id, academy_id=academy_id, sent_at=sent_at
        )
        return LoginInviteResult(sent_at=sent_at)
```

Note: `get_admin_user`'s real signature is `get_admin_user(user_id, academy_id=...)` — match how `MongoUserRepository.get_admin_user` is called elsewhere (`create_admin_user` calls `self.get_admin_user(firebase_uid, academy_id=academy_id)`). Adjust the Protocol/call to keyword style if the repo method requires it.

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest v2/tests/application/identity/test_send_login_invite.py -v`
Expected: 4 passed

- [ ] **Step 5: Commit**

```bash
git add backend/v2/contexts/identity/application/use_cases/send_login_invite.py \
        backend/v2/contexts/identity/application/errors.py \
        backend/v2/tests/application/identity/test_send_login_invite.py
git commit -m "feat(identity): SendLoginInvite use case for set-password emails"
```

---

### Task 2: Infrastructure — reset-link adapter, invite recorder, academy name lookup, detail field

**Files:**
- Modify: `backend/v2/contexts/identity/infrastructure/firebase_admin_adapter.py` (add `generate_password_reset_link`)
- Modify: `backend/v2/contexts/identity/infrastructure/mongo_user_repo.py` (add `record_login_invite`; map `login_invite_sent_at` into `AdminUserDetail`)
- Modify: `backend/v2/contexts/identity/application/use_cases/admin_directory.py` (add `login_invite_sent_at: datetime | None = None` to `AdminUserDetail`)
- Modify: `backend/v2/interfaces/admin/views.py` (add `login_invite_sent_at: datetime | None = None` to `AdminUserDetailView`)
- Create: `backend/v2/contexts/identity/infrastructure/academy_name_lookup.py`

**Interfaces:**
- Consumes: `firebase_admin_auth`, `_ensure_firebase_app`, `asyncio.to_thread` (existing patterns in the adapter).
- Produces: `FirebaseAdminAdapter.generate_password_reset_link(email) -> str`; `MongoUserRepository.record_login_invite(user_id, *, academy_id, sent_at)`; `MongoAcademyNameLookup(db).get_academy_name(academy_id) -> str | None`; `AdminUserDetail.login_invite_sent_at`.

- [ ] **Step 1: Add the adapter method**

In `firebase_admin_adapter.py`, next to `create_user` (same style):

```python
    async def generate_password_reset_link(self, email: str) -> str:
        if firebase_admin_auth is None:
            raise RuntimeError("firebase-admin is required for Firebase auth")
        _ensure_firebase_app()
        link = await asyncio.to_thread(
            firebase_admin_auth.generate_password_reset_link, email
        )
        return str(link)
```

- [ ] **Step 2: Add the invite recorder + detail field**

In `admin_directory.py`, add to `AdminUserDetail`:

```python
    login_invite_sent_at: datetime | None = None
```

(with `from datetime import datetime` if not already imported).

In `views.py`, add the same field to `AdminUserDetailView`:

```python
    login_invite_sent_at: datetime | None = None
```

In `mongo_user_repo.py`:

```python
    async def record_login_invite(
        self, user_id: str, *, academy_id: str, sent_at: datetime
    ) -> None:
        await self.collection.update_one(
            {"academy_id": academy_id, **self._id_filter(user_id)},
            {"$set": {"login_invite_sent_at": sent_at, "updated_at": sent_at}},
        )
```

and in the method that builds `AdminUserDetail` (find `_to_admin_detail` or the mapping inside `get_admin_user`), include:

```python
        login_invite_sent_at=doc.get("login_invite_sent_at"),
```

- [ ] **Step 3: Create the academy name lookup**

Create `backend/v2/contexts/identity/infrastructure/academy_name_lookup.py`. First check what collection/fields the existing "get admin academy" use case reads (grep `composition/admin.py` and the academy settings context for the academies collection name) and use the same; the default below assumes an `academies` collection with `name`/`display_name`:

```python
"""Best-effort academy display-name lookup for outbound emails."""

from typing import Any


class MongoAcademyNameLookup:
    def __init__(self, db: Any) -> None:
        self._collection = db["academies"]

    async def get_academy_name(self, academy_id: str) -> str | None:
        doc = await self._collection.find_one({"academy_id": academy_id})
        if doc is None:
            doc = await self._collection.find_one({"_id": academy_id})
        if doc is None:
            return None
        name = doc.get("display_name") or doc.get("name")
        return str(name) if name else None
```

If the repo already has an academy repository class exposing the name, reuse it instead of this new class and drop this file.

- [ ] **Step 4: Run identity + interface suites (no regressions from the new optional field)**

Run: `pytest v2/tests/application/identity/ v2/tests/interface/test_admin_directory.py -v`
Expected: all pass

- [ ] **Step 5: Commit**

```bash
git add backend/v2/contexts/identity backend/v2/interfaces/admin/views.py
git commit -m "feat(identity): reset-link adapter, invite recorder, academy name lookup"
```

---

### Task 3: Routes, auto-send on creation, composition wiring, interface tests

**Files:**
- Modify: `backend/v2/interfaces/admin/directory_routes.py` (re-send route; auto-send in `create_user` ~line 83 and `bulk_invite_parents` ~line 106)
- Modify: `backend/v2/interfaces/admin/views.py` (add `LoginInviteResponse`)
- Modify: `backend/v2/interfaces/admin/deps.py` (add `send_login_invite: SendLoginInvite | None = None` to `AdminUseCases`)
- Modify: `backend/v2/composition/admin.py` (wire `SendLoginInvite`)
- Modify: `backend/v2/tests/interface/conftest.py` (fake invite sender)
- Test: `backend/v2/tests/interface/test_admin_directory.py`

**Interfaces:**
- Consumes: Task 1's `SendLoginInvite`/`LoginInviteResult`/`LoginInviteSendFailed`; Task 2's infrastructure.
- Produces: `POST /api/v2/admin/users/{user_id}/login-invite` → 200 `{"sent_at": "<ISO-8601 UTC>"}`; `create_user`/`bulk_invite_parents` auto-send invites for parent-role creations (best-effort). Task 4's frontend calls the re-send endpoint.

- [ ] **Step 1: Write the failing interface tests**

Append to `backend/v2/tests/interface/test_admin_directory.py` (adapt fake user ids to the conftest seed — use an id the fake invite sender knows):

```python
def test_admin_resends_login_invite(admin_client):
    r = admin_client.post("/api/v2/admin/users/coach-1/login-invite")
    assert r.status_code == 200, r.text
    assert r.json()["sent_at"] is not None


def test_login_invite_unknown_user_404(admin_client):
    r = admin_client.post("/api/v2/admin/users/nope/login-invite")
    assert r.status_code == 404


def test_login_invite_wrong_persona_404(coach_on_admin_client):
    r = coach_on_admin_client.post("/api/v2/admin/users/coach-1/login-invite")
    assert r.status_code == 404
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest v2/tests/interface/test_admin_directory.py -v`
Expected: new tests FAIL (404/405 — route missing)

- [ ] **Step 3: Implement views, route, auto-send, deps, composition, conftest fake**

In `views.py`:

```python
class LoginInviteResponse(BaseModel):
    sent_at: datetime
```

(import `datetime` if needed.)

In `deps.py`, add to `AdminUseCases`:

```python
    send_login_invite: SendLoginInvite | None = None
```

In `directory_routes.py` add the route:

```python
@router.post("/users/{user_id}/login-invite", response_model=LoginInviteResponse)
async def send_login_invite(
    user_id: str,
    claims: AuthClaims = Depends(require_persona("admin")),
    use_cases: AdminUseCases = Depends(get_admin_use_cases),
) -> LoginInviteResponse:
    use_case = use_cases.send_login_invite
    if use_case is None:
        raise HTTPException(status_code=503, detail="Login invites are not configured")
    try:
        result = await use_case.execute(user_id, academy_id=claims.academy_id)
    except LoginInviteSendFailed as exc:
        raise HTTPException(
            status_code=502, detail="Could not send the invite email"
        ) from exc
    return LoginInviteResponse(sent_at=result.sent_at)
```

(`UserNotFound` → 404 via the existing exception handlers, same as other directory routes.)

Auto-send in `create_user` — after `user = await use_case.execute(...)`, before the return:

```python
    invite = use_cases.send_login_invite
    if invite is not None and payload.role == "parent":
        try:
            await invite.execute(user.user_id, academy_id=claims.academy_id)
        except Exception:
            logger.exception("login invite failed for %s", user.user_id)
```

Auto-send in `bulk_invite_parents` — inside the success branch after `results.append(...)`/`created += 1`:

```python
            invite = use_cases.send_login_invite
            if invite is not None:
                try:
                    await invite.execute(user.user_id, academy_id=claims.academy_id)
                except Exception:
                    logger.exception("login invite failed for %s", item.email)
```

In `composition/admin.py`, near the `_email_sender` construction (~line 2825) and `create_admin_user` wiring (~line 3361):

```python
    send_login_invite = SendLoginInvite(
        users=users_r,
        links=get_firebase_admin_adapter(),
        sender=_email_sender,
        academies=MongoAcademyNameLookup(db),
    )
```

then `send_login_invite=send_login_invite,` in the `AdminUseCases(...)` construction (~line 5677). Import `SendLoginInvite`, `MongoAcademyNameLookup`, and `get_firebase_admin_adapter` following the file's existing import conventions (the user-repo module already imports the adapter accessor — reuse it). If `_email_sender` is not in scope at that point, build the sender with the same env-gated pattern used at lines 2817–2825.

In `tests/interface/conftest.py`, add a fake and wire it:

```python
class _FakeLoginInviteSender:
    def __init__(self) -> None:
        self.sent: list[str] = []
        self.known = {"coach-1", "u-admin", "p-1"}

    async def execute(self, user_id, *, academy_id):
        from datetime import UTC, datetime

        from backend.v2.contexts.identity.application.errors import UserNotFound
        from backend.v2.contexts.identity.application.use_cases.send_login_invite import (
            LoginInviteResult,
        )

        if user_id not in self.known:
            raise UserNotFound(user_id)
        self.sent.append(user_id)
        return LoginInviteResult(sent_at=datetime.now(UTC))
```

Wire: `send_login_invite=_FakeLoginInviteSender(),` in `_build_admin_use_cases`'s `AdminUseCases(...)` call. (A plain duck-typed fake is fine — the route only calls `.execute`.)

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest v2/tests/interface/test_admin_directory.py v2/tests/application/identity/ -v`
Expected: all pass

- [ ] **Step 5: Full backend gate**

Run: `cd backend && ruff format --check . && ruff check . && pytest v2/tests -q`
Expected: clean

- [ ] **Step 6: Commit**

```bash
git add backend/v2/interfaces/admin backend/v2/composition/admin.py backend/v2/tests
git commit -m "feat(admin): login-invite endpoint + auto-send on parent creation"
```

---

### Task 4: Frontend — Add-user page, invite button + indicator

**Files:**
- Modify: `frontend/lib/api/admin.ts` (add `createAdminUser`, `sendLoginInvite`; extend `AdminUserDetail` type)
- Create: `frontend/app/(admin)/admin/users/new/page.tsx`
- Modify: `frontend/app/(admin)/admin/users/page.tsx` (add "Add user" link)
- Modify: `frontend/app/(admin)/admin/users/[userId]/page.tsx` (invite panel)

**Interfaces:**
- Consumes: backend endpoints from Task 3; `apiFetch`; existing `MutationMessages`, `Button` components; React Query + `queryKeys.admin.users(...)`.
- Produces: admin can create a user (name/email/phone/role) and send/re-send login invites; detail page shows "Invite sent {date}".

- [ ] **Step 1: API functions + type**

In `frontend/lib/api/admin.ts`, extend `AdminUserDetail`:

```ts
export interface AdminUserDetail extends AdminUserView {
  roles: AdminUserRole[];
  linked_student_count: number;
  session_count: number;
  login_invite_sent_at?: string | null;
}
```

and add:

```ts
export function createAdminUser(payload: {
  role: AdminUserRole;
  display_name: string;
  email: string;
  phone?: string | null;
  reason?: string;
}): Promise<AdminUserDetail> {
  return apiFetch<AdminUserDetail>(`/admin/users`, {
    method: "POST",
    body: JSON.stringify({ reason: "manual user creation", ...payload }),
  });
}

export function sendLoginInvite(userId: string): Promise<{ sent_at: string }> {
  return apiFetch<{ sent_at: string }>(
    `/admin/users/${encodeURIComponent(userId)}/login-invite`,
    { method: "POST" },
  );
}
```

- [ ] **Step 2: Add-user page**

Create `frontend/app/(admin)/admin/users/new/page.tsx`:

```tsx
"use client";

import { useState } from "react";
import { useRouter } from "next/navigation";
import { useMutation } from "@tanstack/react-query";

import { createAdminUser, type AdminUserRole } from "@/lib/api/admin";
import { Button } from "@/components/ds/button";

const roleOptions: AdminUserRole[] = ["parent", "coach", "admin"];

export default function NewAdminUserPage() {
  const router = useRouter();
  const [displayName, setDisplayName] = useState("");
  const [email, setEmail] = useState("");
  const [phone, setPhone] = useState("");
  const [role, setRole] = useState<AdminUserRole>("parent");
  const [error, setError] = useState<string | null>(null);

  const mutation = useMutation({
    mutationFn: () =>
      createAdminUser({
        role,
        display_name: displayName,
        email,
        phone: phone || null,
      }),
    onSuccess: (user) => {
      router.push(`/admin/users/${user.user_id}`);
    },
    onError: (err: unknown) => {
      setError(err instanceof Error ? err.message : "Could not create user.");
    },
  });

  return (
    <div className="mx-auto max-w-lg space-y-4 p-4">
      <h1 className="text-lg font-semibold text-rally-ink">Add user</h1>
      <p className="text-sm text-slate-500">
        Parents created here get a &ldquo;set your password&rdquo; email
        automatically, so they can log in with any email address — no Google
        account needed.
      </p>
      <form
        className="space-y-3 rounded-lg border border-rally-line bg-white p-4"
        onSubmit={(e) => {
          e.preventDefault();
          setError(null);
          mutation.mutate();
        }}
      >
        <label className="block text-sm">
          <span className="text-slate-600">Full name</span>
          <input
            value={displayName}
            onChange={(e) => setDisplayName(e.target.value)}
            required
            maxLength={120}
            className="mt-1 w-full rounded-md border border-rally-line px-2 py-1.5 text-sm"
            data-testid="new-user-name"
          />
        </label>
        <label className="block text-sm">
          <span className="text-slate-600">Email</span>
          <input
            type="email"
            value={email}
            onChange={(e) => setEmail(e.target.value)}
            required
            maxLength={254}
            className="mt-1 w-full rounded-md border border-rally-line px-2 py-1.5 text-sm"
            data-testid="new-user-email"
          />
        </label>
        <label className="block text-sm">
          <span className="text-slate-600">Phone (optional)</span>
          <input
            value={phone}
            onChange={(e) => setPhone(e.target.value)}
            maxLength={40}
            className="mt-1 w-full rounded-md border border-rally-line px-2 py-1.5 text-sm"
          />
        </label>
        <label className="block text-sm">
          <span className="text-slate-600">Role</span>
          <select
            value={role}
            onChange={(e) => setRole(e.target.value as AdminUserRole)}
            className="mt-1 w-full rounded-md border border-rally-line px-2 py-1.5 text-sm"
            data-testid="new-user-role"
          >
            {roleOptions.map((r) => (
              <option key={r} value={r}>
                {r}
              </option>
            ))}
          </select>
        </label>
        {error && (
          <p role="alert" className="rounded-md border border-red-200 bg-red-50 p-2 text-sm text-red-700">
            {error}
          </p>
        )}
        <Button type="submit" size="sm" disabled={mutation.isPending}>
          {mutation.isPending ? "Creating…" : "Create user"}
        </Button>
      </form>
    </div>
  );
}
```

In `frontend/app/(admin)/admin/users/page.tsx`, add next to the role filter chips:

```tsx
<Link
  href="/admin/users/new"
  className="rounded-md px-3 py-1.5 text-sm font-medium text-white"
  style={{ background: "var(--rally-cobalt)" }}
  data-testid="add-user-link"
>
  Add user
</Link>
```

(import `Link` from `next/link` if not present; match the page's existing layout for the filter row.)

- [ ] **Step 3: Invite panel on user detail**

In `frontend/app/(admin)/admin/users/[userId]/page.tsx`, add a `LoginInvitePanel` and render it alongside the other panels:

```tsx
function LoginInvitePanel({
  user,
  onSaved,
}: {
  user: AdminUserDetail;
  onSaved: () => void;
}) {
  const [submitError, setSubmitError] = useState<string | null>(null);
  const [submitOk, setSubmitOk] = useState(false);

  const mutation = useMutation({
    mutationFn: () => sendLoginInvite(user.user_id),
    onSuccess: () => {
      setSubmitError(null);
      setSubmitOk(true);
      onSaved();
    },
    onError: (err: unknown) => {
      setSubmitOk(false);
      setSubmitError(err instanceof Error ? err.message : "Could not send invite.");
    },
  });

  return (
    <section className="space-y-3 rounded-lg border border-rally-line bg-white p-4">
      <h2 className="text-sm font-semibold text-rally-ink">Login invite</h2>
      <p className="text-xs text-slate-500">
        Sends a &ldquo;set your password&rdquo; email so this user can log in
        with email + password (works with any email provider).
      </p>
      <p className="text-sm text-slate-600" data-testid="invite-sent-at">
        {user.login_invite_sent_at
          ? `Invite sent ${new Date(user.login_invite_sent_at).toLocaleDateString()}`
          : "No invite sent yet"}
      </p>
      <MutationMessages error={submitError} ok={submitOk} />
      <Button
        type="button"
        size="sm"
        variant="secondary"
        disabled={mutation.isPending}
        onClick={() => mutation.mutate()}
        data-testid="send-login-invite"
      >
        {mutation.isPending
          ? "Sending…"
          : user.login_invite_sent_at
            ? "Re-send invite"
            : "Send login invite"}
      </Button>
    </section>
  );
}
```

Import `sendLoginInvite` from `@/lib/api/admin`; pass the same `onSaved` refetch callback the other panels use.

- [ ] **Step 4: Typecheck + lint**

Run: `cd frontend && npm run typecheck && npm run lint`
Expected: clean

- [ ] **Step 5: Commit**

```bash
git add frontend/lib/api/admin.ts "frontend/app/(admin)/admin/users/new/page.tsx" \
        "frontend/app/(admin)/admin/users/page.tsx" "frontend/app/(admin)/admin/users/[userId]/page.tsx"
git commit -m "feat(admin-ui): add-user page and login invite send/re-send"
```

---

### Task 5: Student linking check + end-to-end verification

**Files:**
- Possibly modify: none (verification task; only file changes if the linking gap below is real)

- [ ] **Step 1: Verify how the already-registered kids attach to the new parent account**

Students reference their parent via `Student.parent_id` (`backend/v2/contexts/enrollment/domain/models.py:75`). For each real family being invited, confirm what `parent_id` their students currently carry (staging/dev Mongo shell, synthetic example):

```
db.students.find({academy_id: "<acad>"}, {student_id: 1, parent_id: 1, display_name: 1})
```

- If students carry a parent user_id whose `users` doc already has the parent's email → `create_admin_user` will fail with "email already exists"; the correct flow is the **existing** user's detail page → "Send login invite" (the account exists; only credentials are missing). This is the expected case for kids registered with the parent's email on file.
- If students carry NO parent link or a placeholder → linking is a data fix: set `students.parent_id` to the new parent's `user_id` via the existing admin student edit surface if one exists, or a one-off scripted update reviewed with the user. Do NOT build a new linking UI in this slice unless the data shows it's needed for more than a handful of families (YAGNI — record the finding and ask).

- [ ] **Step 2: Backend + frontend full gates**

Run: `cd backend && ruff format --check . && ruff check . && pytest v2/tests -q`
Run: `cd frontend && npm run typecheck && npm run lint`
Expected: clean

- [ ] **Step 3: End-to-end staging pass**

1. Ensure staging has `email_delivery_enabled` + `resend_api_key` set (else the Stub records instead of sending — fine for a dry run; check server logs for the stubbed send).
2. As admin: Users → Add user → role parent, a test Yahoo/Hotmail-style address you control.
3. Confirm the "Set your password" email arrives with academy branding and a working link.
4. Set a password; confirm Firebase marks the email verified (Firebase console → user).
5. Log in at `/login` with email + password → lands on `/parent/payments`; kids visible if linked.
6. On the user detail page, confirm "Invite sent {date}" and re-send works.

- [ ] **Step 4: Release notes + commit**

Add `docs/release-notes/2026-07-09-feat-parent-login-invite.md` following the existing release-note format, commit.
