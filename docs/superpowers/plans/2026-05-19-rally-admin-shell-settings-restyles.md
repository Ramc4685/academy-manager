# Rally Admin — Shell + Settings + Page Restyles Implementation Plan

> **For agentic workers:** REQUIRED: Use superpowers:subagent-driven-development (if subagents available) or superpowers:executing-plans to implement this plan. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Bring the admin persona on canonical `frontend/` to Rally design parity — close out Phase 3, build a 7-panel Settings page with backing endpoints, and restyle the 12 remaining admin pages — without touching coach/parent personas.

**Architecture:** Sidebar shell from Phase 2 (already committed `5d151e7`) stays. Settings owns its own tab strip + 7 panel components, each self-contained with TanStack Query. New BFF endpoints under `backend/v2/interfaces/admin/` are small additive resources on the existing academy doc (no new contexts). Restyles preserve every BFF call and action; replace Tailwind chrome with `components/ds/*` primitives.

**Tech Stack:** Next.js 15 (canonical `frontend/`), React 19, TanStack Query, Radix Dialog, Tailwind + Rally tokens, FastAPI (`backend/v2/`), Motor/PyMongo, pytest, Playwright.

**Branch:** `feat/rally-admin-foundation`

**Spec:** [docs/superpowers/specs/2026-05-19-rally-admin-shell-settings-restyles-design.md](../specs/2026-05-19-rally-admin-shell-settings-restyles-design.md)

---

## File Structure

### Frontend (canonical `frontend/`)

**New files (this plan):**

```
frontend/
├── app/(admin)/admin/
│   └── settings/
│       └── page.tsx                              # 7-tab Settings shell (rewrite)
├── components/admin/settings/
│   ├── academy-panel.tsx                         # Real read/write
│   ├── fees-panel.tsx                            # Real read/write
│   ├── gateway-panel.tsx                         # Real read-only
│   ├── notify-panel.tsx                          # Real read/write
│   ├── roles-panel.tsx                           # Real read/write (+ conditional invite)
│   ├── branding-panel.tsx                        # Coming-next card
│   ├── data-panel.tsx                            # CSV exports real + deletion Coming-next
│   ├── settings-tabs.tsx                         # Shared Rally tab strip (used by page.tsx)
│   └── coming-next-card.tsx                      # Shared empty-state primitive for deferred panels
└── e2e/specs/
    └── admin-shell.spec.ts                       # Already drafted in Phase 3, finalize + expand
```

**Modified files (this plan):**

```
frontend/
├── app/(admin)/admin/
│   ├── page.tsx                                  # A0 hotfix: defensive null on KPIs
│   ├── students/page.tsx                         # C1 restyle
│   ├── users/page.tsx                            # C1 restyle
│   ├── waitlist/page.tsx                         # C1 restyle
│   ├── pause-requests/page.tsx                   # C1 restyle
│   ├── dues/page.tsx                             # C2 restyle
│   ├── reports/page.tsx                          # C2 restyle
│   ├── coach-payslip/page.tsx                    # C2 restyle
│   ├── expenses/page.tsx                         # C3 promote real impl from finance/page.tsx
│   ├── payouts/page.tsx                          # C3 promote real impl from finance/page.tsx
│   ├── finance/page.tsx                          # C3 — decision captured in commit msg; D2 deletes
│   ├── audit-logs/page.tsx                       # C4 restyle
│   ├── messages/page.tsx                         # already uncommitted; lands in A1
│   ├── sessions/page.tsx                         # already uncommitted; lands in A1
│   ├── sessions/[id]/page.tsx                    # already uncommitted; lands in A1
│   └── payments/page.tsx                         # already uncommitted; lands in A1
├── app/(shared)/messages/page.tsx                # already uncommitted; lands in A1
├── components/admin/screen-meta.ts               # already uncommitted; lands in A1
└── lib/api/admin.ts                              # B1-B3 type & client additions; D1 if surfaced
```

**Deleted files (this plan):**

```
frontend/app/(admin)/admin/
├── billing/page.tsx                              # D2 — superseded by payments/page.tsx
├── comms/page.tsx                                # already git-renamed to messages/ in Phase 3
└── finance/page.tsx                              # D2 (conditional on C3 decision)
```

### Backend (`backend/v2/`)

**New files (this plan):**

```
backend/v2/
├── interfaces/admin/
│   └── academy_routes.py                         # Settings: academy, fees, gateway, notifications
├── contexts/identity/application/
│   ├── get_academy_use_case.py                   # B1
│   ├── update_academy_use_case.py                # B1
│   ├── get_academy_fees_use_case.py              # B2 (default context: identity, per spec)
│   ├── update_academy_fees_use_case.py           # B2
│   ├── get_academy_gateway_use_case.py           # B3
│   ├── get_academy_notifications_use_case.py     # B2
│   ├── update_academy_notifications_use_case.py  # B2
│   └── change_user_role_use_case.py              # B3
└── tests/
    ├── contract/admin/test_academy_contract.py   # B1 contract
    ├── contract/admin/test_academy_fees_contract.py        # B2
    ├── contract/admin/test_academy_gateway_contract.py     # B3
    ├── contract/admin/test_academy_notifications_contract.py # B2
    ├── contract/admin/test_user_role_contract.py # B3
    ├── application/identity/test_academy_use_cases.py      # B1+B2+B3
    └── interface/admin/test_academy_routes.py    # B1 onwards
```

**Modified files (this plan):**

```
backend/v2/
├── interfaces/admin/router.py                    # B1: register academy_routes
├── interfaces/admin/directory_routes.py          # B3: add PATCH /users/{id}/role (+ optional invite)
├── interfaces/admin/views.py                     # B1-B3 DTOs; D1 if coach_name surfaces
└── contexts/identity/infrastructure/             # B1-B3: extend academy repo with optional fields
```

---

## Chunk 1: Session 1 — Phase 3 close-out (A0 + A1)

This chunk lands in the current conversation. It's bounded by the work already done but uncommitted in the worktree.

### Task A0: Dashboard hotfix — defensive null on KPIs

**Files:**
- Modify: `frontend/app/(admin)/admin/page.tsx:82`

**Context:** The earlier Playwright run surfaced `TypeError: Cannot read properties of undefined (reading 'length')` at `sessionsQuery.data?.sessions.length`. When the backend returns a partial / stubbed payload, `sessions` can be `undefined` even when `data` is defined.

- [ ] **A0.1: Apply the defensive optional chain**

Edit `frontend/app/(admin)/admin/page.tsx` line 82 area:

```tsx
// Before:
const todayCount = sessionsQuery.data?.sessions.length ?? 0;

// After:
const todayCount = sessionsQuery.data?.sessions?.length ?? 0;
```

Apply the same pattern to any other `?.field.length`, `?.field.slice`, etc. on lines 60–95.

- [ ] **A0.2: Typecheck**

```bash
cd frontend && pnpm typecheck
```

Expected: no errors.

- [ ] **A0.3: Build**

```bash
cd frontend && pnpm build
```

Expected: build succeeds. Admin landing chunk < 300 KB.

### Task A1: Phase 3 close-out commit + Playwright smoke

**Files (all already uncommitted in worktree):**
- Modify: `frontend/app/(admin)/admin/page.tsx`
- Modify: `frontend/app/(admin)/admin/sessions/page.tsx`
- Modify: `frontend/app/(admin)/admin/sessions/[id]/page.tsx`
- Modify: `frontend/app/(admin)/admin/payments/page.tsx`
- Modify: `frontend/app/(admin)/admin/messages/page.tsx` (renamed from `comms/` in Phase 3)
- Modify: `frontend/app/(shared)/messages/page.tsx`
- Modify: `frontend/components/admin/screen-meta.ts`
- Add: `frontend/e2e/specs/admin-shell.spec.ts`

- [ ] **A1.1: Run the admin-shell smoke spec on a non-colliding port**

```bash
cd frontend && PLAYWRIGHT_PORT=3801 pnpm exec playwright test e2e/specs/admin-shell.spec.ts --reporter=list
```

Expected: 12 passed. Two `shell renders three nav groups` failures from the prior run are fixed by the drawer-open assertion (already applied).

If anything still fails on mobile viewports, prefer adding `data-testid` markers over rewriting assertions — never weaken a real test to pass a flaky run.

- [ ] **A1.2: Confirm cross-persona regression smoke**

In a browser at `http://localhost:3801`:
- `/coach/today` loads without console error.
- `/parent/dashboard` (or first reachable parent page) loads without console error.

If a console error appears that's not in the benign-warning ignore-list (`/Download the React DevTools/i`, `/Fast Refresh/i`, `/HMR/i`, `/webpack-internal/i`), capture it and fix before commit.

- [ ] **A1.3: Stage + commit**

```bash
git add frontend/app/\(admin\)/admin/page.tsx \
        frontend/app/\(admin\)/admin/sessions/ \
        frontend/app/\(admin\)/admin/payments/page.tsx \
        frontend/app/\(admin\)/admin/messages/page.tsx \
        frontend/app/\(shared\)/messages/page.tsx \
        frontend/components/admin/screen-meta.ts \
        frontend/e2e/specs/admin-shell.spec.ts
git status --short
```

Expected: only the 7 listed paths are staged.

- [ ] **A1.4: Commit with multi-line message**

```bash
git commit -m "$(cat <<'EOF'
feat(frontend/admin): Phase 3 restyle - dashboard/sessions/payments/messages

- Dashboard rebuilt with Rally Card + Chip + BigNum + LaneHeader. Real
  data only: listAdminSessions(today), listAdminPayments, getRevenue.
  Dropped the "Needs your attention" section entirely (no real attention
  endpoint exists yet; will be a follow-on with /admin/dashboard/attention).
- Sessions list + detail restyled. Preserves table/calendar toggle,
  create-session dialog, cancel-with-confirm, roster (pause/resume/
  move/remove), waitlist (promote/skip/remove), transfer dialog.
- Payments promoted from /admin/billing into /admin/payments per the
  Rally route map. /admin/billing is left intact (stale) until D2
  cleanup; no reverse redirect added without user approval. Refund
  control disabled when payment is not refund-eligible.
- comms/page.tsx renamed to messages/page.tsx (git mv). Backend BFF
  paths under /admin/messages/* unchanged. (shared)/messages updated
  to link to /admin/messages.
- screen-meta.ts: messages nav item href points to /admin/messages;
  match function accepts both /comms and /messages so the back link
  highlights correctly during the rename window.
- admin-shell.spec.ts: Playwright smoke covering shell nav groups + 5
  Phase 3 routes mounting + session detail. Filters benign warnings
  (Fast Refresh, HMR, React DevTools).
- Defensive optional chain on dashboard KPIs after a TypeError surfaced
  in the smoke run.

Phase 3 complete. Phase 4+ (Settings deep dive + remaining restyles)
lands per docs/superpowers/specs/2026-05-19-rally-admin-shell-settings-
restyles-design.md.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

- [ ] **A1.5: Verify the commit**

```bash
git log --oneline -3
git status --short
```

Expected: new HEAD is the Phase 3 close-out commit; working tree clean.

---

## Chunk 2: Session 2 — Settings B1 + B2 (Academy + Fees + Notify)

### Architectural context (read before starting)

The user-confirmed default per the spec: fees + notifications live in the **`identity` context** (where the academy doc already lives). Capture this in the B1 commit message; subsequent panels follow without re-prompting.

Read these files before writing anything:
- `backend/v2/interfaces/admin/router.py` — to understand how new route files are registered.
- `backend/v2/interfaces/admin/directory_routes.py` — closest precedent for admin BFF routes; mirror its structure (deps, view models, error handling).
- `backend/v2/interfaces/admin/views.py` — DTO patterns; add new view models here.
- `backend/v2/contexts/identity/application/` — existing use-case shape (constructor takes repos, `execute(input)` returns output).
- `backend/v2/contexts/identity/infrastructure/` — find the academy/Mongo repo. New optional fields read with defaults; writes use `$set` on the existing doc.
- `backend/v2/tests/contract/admin/` — find an existing contract test to mirror.
- `frontend/lib/api/admin.ts` — extend at the end; preserve typed-fetch pattern (`apiFetch<T>("/admin/…", { method })`).
- `frontend/components/ds/*` — primitives are already there; do not re-implement.

### Task B1.1: Academy DTO + view model

**Files:**
- Modify: `backend/v2/interfaces/admin/views.py`

- [ ] **B1.1.1: Add pydantic view models for academy**

Add to `views.py`:

```python
from typing import Optional
from pydantic import BaseModel

class AdminAcademyView(BaseModel):
    academy_id: str
    display_name: str
    timezone: str
    contact_email: Optional[str] = None
    contact_phone: Optional[str] = None
    hours_text: Optional[str] = None
    address: Optional[str] = None

class UpdateAdminAcademyRequest(BaseModel):
    display_name: Optional[str] = None
    timezone: Optional[str] = None
    contact_email: Optional[str] = None
    contact_phone: Optional[str] = None
    hours_text: Optional[str] = None
    address: Optional[str] = None
```

- [ ] **B1.1.2: Typecheck backend**

```bash
cd backend && source .venv/bin/activate && python -c "from v2.interfaces.admin.views import AdminAcademyView, UpdateAdminAcademyRequest"
```

Expected: no error.

### Task B1.2: Get-academy use case (TDD)

**Files:**
- Create: `backend/v2/contexts/identity/application/get_academy_use_case.py`
- Test: `backend/v2/tests/application/identity/test_academy_use_cases.py`

- [ ] **B1.2.1: Write the failing test**

```python
# backend/v2/tests/application/identity/test_academy_use_cases.py
import pytest
from unittest.mock import AsyncMock
from v2.contexts.identity.application.get_academy_use_case import (
    GetAcademyUseCase, GetAcademyInput,
)

@pytest.mark.asyncio
async def test_get_academy_returns_view_when_found():
    repo = AsyncMock()
    repo.find_by_id.return_value = {
        "_id": "acad-1",
        "display_name": "Court 7",
        "timezone": "America/New_York",
    }
    use_case = GetAcademyUseCase(academy_repo=repo)
    output = await use_case.execute(GetAcademyInput(academy_id="acad-1"))
    assert output.academy_id == "acad-1"
    assert output.display_name == "Court 7"
    assert output.timezone == "America/New_York"
    assert output.contact_email is None  # absent optional field

@pytest.mark.asyncio
async def test_get_academy_raises_when_missing():
    repo = AsyncMock()
    repo.find_by_id.return_value = None
    use_case = GetAcademyUseCase(academy_repo=repo)
    with pytest.raises(LookupError):
        await use_case.execute(GetAcademyInput(academy_id="missing"))
```

- [ ] **B1.2.2: Run test, expect import failure**

```bash
cd backend && source .venv/bin/activate && pytest v2/tests/application/identity/test_academy_use_cases.py -v
```

Expected: ImportError (`get_academy_use_case` not found).

- [ ] **B1.2.3: Implement minimal use case**

```python
# backend/v2/contexts/identity/application/get_academy_use_case.py
from dataclasses import dataclass
from typing import Optional, Protocol

class AcademyRepo(Protocol):
    async def find_by_id(self, academy_id: str) -> Optional[dict]: ...

@dataclass(frozen=True)
class GetAcademyInput:
    academy_id: str

@dataclass(frozen=True)
class GetAcademyOutput:
    academy_id: str
    display_name: str
    timezone: str
    contact_email: Optional[str] = None
    contact_phone: Optional[str] = None
    hours_text: Optional[str] = None
    address: Optional[str] = None

class GetAcademyUseCase:
    def __init__(self, academy_repo: AcademyRepo):
        self._repo = academy_repo

    async def execute(self, input: GetAcademyInput) -> GetAcademyOutput:
        doc = await self._repo.find_by_id(input.academy_id)
        if not doc:
            raise LookupError(f"academy {input.academy_id} not found")
        return GetAcademyOutput(
            academy_id=doc["_id"],
            display_name=doc.get("display_name", ""),
            timezone=doc.get("timezone", "UTC"),
            contact_email=doc.get("contact_email"),
            contact_phone=doc.get("contact_phone"),
            hours_text=doc.get("hours_text"),
            address=doc.get("address"),
        )
```

- [ ] **B1.2.4: Run test, expect pass**

```bash
cd backend && pytest v2/tests/application/identity/test_academy_use_cases.py -v
```

Expected: 2 passed.

### Task B1.3: Update-academy use case (TDD)

**Files:**
- Create: `backend/v2/contexts/identity/application/update_academy_use_case.py`
- Test: append to `backend/v2/tests/application/identity/test_academy_use_cases.py`

- [ ] **B1.3.1: Add the failing test**

```python
# append to test_academy_use_cases.py
from v2.contexts.identity.application.update_academy_use_case import (
    UpdateAcademyUseCase, UpdateAcademyInput,
)

@pytest.mark.asyncio
async def test_update_academy_partial_set():
    repo = AsyncMock()
    repo.update_by_id.return_value = {
        "_id": "acad-1",
        "display_name": "Court 7",
        "timezone": "America/New_York",
        "contact_email": "ops@court7.example",
    }
    use_case = UpdateAcademyUseCase(academy_repo=repo)
    output = await use_case.execute(UpdateAcademyInput(
        academy_id="acad-1", contact_email="ops@court7.example",
    ))
    assert output.contact_email == "ops@court7.example"
    # Verify only non-None fields are passed to the repo:
    repo.update_by_id.assert_awaited_once_with(
        "acad-1", {"contact_email": "ops@court7.example"},
    )

@pytest.mark.asyncio
async def test_update_academy_raises_when_missing():
    repo = AsyncMock()
    repo.update_by_id.return_value = None
    use_case = UpdateAcademyUseCase(academy_repo=repo)
    with pytest.raises(LookupError):
        await use_case.execute(UpdateAcademyInput(
            academy_id="missing", display_name="X",
        ))
```

- [ ] **B1.3.2: Run, expect import failure**

```bash
cd backend && pytest v2/tests/application/identity/test_academy_use_cases.py -v
```

Expected: 2 pass + 2 fail (ImportError on new tests).

- [ ] **B1.3.3: Implement update use case**

```python
# backend/v2/contexts/identity/application/update_academy_use_case.py
from dataclasses import asdict, dataclass
from typing import Optional, Protocol
from .get_academy_use_case import GetAcademyOutput

class AcademyWriteRepo(Protocol):
    async def update_by_id(self, academy_id: str, fields: dict) -> Optional[dict]: ...

@dataclass(frozen=True)
class UpdateAcademyInput:
    academy_id: str
    display_name: Optional[str] = None
    timezone: Optional[str] = None
    contact_email: Optional[str] = None
    contact_phone: Optional[str] = None
    hours_text: Optional[str] = None
    address: Optional[str] = None

class UpdateAcademyUseCase:
    def __init__(self, academy_repo: AcademyWriteRepo):
        self._repo = academy_repo

    async def execute(self, input: UpdateAcademyInput) -> GetAcademyOutput:
        patch = {k: v for k, v in asdict(input).items() if k != "academy_id" and v is not None}
        if not patch:
            # No-op — caller passed empty patch
            doc = await self._repo.update_by_id(input.academy_id, {})
        else:
            doc = await self._repo.update_by_id(input.academy_id, patch)
        if not doc:
            raise LookupError(f"academy {input.academy_id} not found")
        return GetAcademyOutput(
            academy_id=doc["_id"],
            display_name=doc.get("display_name", ""),
            timezone=doc.get("timezone", "UTC"),
            contact_email=doc.get("contact_email"),
            contact_phone=doc.get("contact_phone"),
            hours_text=doc.get("hours_text"),
            address=doc.get("address"),
        )
```

- [ ] **B1.3.4: Run, expect pass**

```bash
cd backend && pytest v2/tests/application/identity/test_academy_use_cases.py -v
```

Expected: 4 passed.

### Task B1.4: Academy repo extension

**Files:**
- Modify: existing academy/mongo repo in `backend/v2/contexts/identity/infrastructure/`

The exact file name varies; locate via:
```bash
cd backend && grep -rn "class.*AcademyRepo\|class.*Academy.*Repo" v2/contexts/identity/infrastructure/
```

- [ ] **B1.4.1: Add `find_by_id` and `update_by_id` methods if not present**

Pattern (Motor/Mongo):

```python
async def find_by_id(self, academy_id: str) -> Optional[dict]:
    return await self._collection.find_one({"_id": academy_id})

async def update_by_id(self, academy_id: str, fields: dict) -> Optional[dict]:
    if not fields:
        return await self.find_by_id(academy_id)
    result = await self._collection.find_one_and_update(
        {"_id": academy_id},
        {"$set": fields},
        return_document=True,
    )
    return result
```

If methods already exist with these signatures, skip.

- [ ] **B1.4.2: Run any existing repo tests**

```bash
cd backend && pytest v2/tests/ -k "identity and repo" -v
```

Expected: existing tests pass.

### Task B1.5: BFF router for academy (TDD)

**Files:**
- Create: `backend/v2/interfaces/admin/academy_routes.py`
- Modify: `backend/v2/interfaces/admin/router.py` (register the new sub-router)
- Test: `backend/v2/tests/interface/admin/test_academy_routes.py`

- [ ] **B1.5.1: Write the failing interface test**

```python
# backend/v2/tests/interface/admin/test_academy_routes.py
from fastapi.testclient import TestClient

def test_get_academy_returns_view(test_client: TestClient, seeded_admin_token: str, seeded_academy_id: str):
    res = test_client.get(
        "/api/v2/admin/academy",
        headers={"Authorization": f"Bearer {seeded_admin_token}"},
    )
    assert res.status_code == 200
    body = res.json()
    assert body["academy_id"] == seeded_academy_id
    assert "display_name" in body
    assert "timezone" in body

def test_patch_academy_updates_field(test_client: TestClient, seeded_admin_token: str):
    res = test_client.patch(
        "/api/v2/admin/academy",
        headers={"Authorization": f"Bearer {seeded_admin_token}"},
        json={"contact_email": "ops@court7.example"},
    )
    assert res.status_code == 200
    assert res.json()["contact_email"] == "ops@court7.example"

def test_get_academy_unauthorized_without_admin(test_client: TestClient, seeded_coach_token: str):
    res = test_client.get(
        "/api/v2/admin/academy",
        headers={"Authorization": f"Bearer {seeded_coach_token}"},
    )
    assert res.status_code in (401, 403)
```

If the test fixtures `seeded_admin_token` / `seeded_coach_token` / `seeded_academy_id` don't exist, locate the existing admin interface tests and reuse their fixture pattern. Read at least one existing file under `backend/v2/tests/interface/admin/` first.

- [ ] **B1.5.2: Run, expect 404 / import failure**

```bash
cd backend && pytest v2/tests/interface/admin/test_academy_routes.py -v
```

- [ ] **B1.5.3: Implement the router**

```python
# backend/v2/interfaces/admin/academy_routes.py
from fastapi import APIRouter, Depends, HTTPException, status

from v2.contexts.identity.application.get_academy_use_case import (
    GetAcademyUseCase, GetAcademyInput,
)
from v2.contexts.identity.application.update_academy_use_case import (
    UpdateAcademyUseCase, UpdateAcademyInput,
)
from .deps import require_admin, AdminPrincipal, get_academy_use_case_deps
from .views import AdminAcademyView, UpdateAdminAcademyRequest

router = APIRouter(prefix="/admin", tags=["admin-academy"])

@router.get("/academy", response_model=AdminAcademyView)
async def get_academy(
    principal: AdminPrincipal = Depends(require_admin),
    use_case: GetAcademyUseCase = Depends(get_academy_use_case_deps),
):
    try:
        output = await use_case.execute(GetAcademyInput(academy_id=principal.academy_id))
    except LookupError:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "academy not found")
    return AdminAcademyView(**output.__dict__)

@router.patch("/academy", response_model=AdminAcademyView)
async def patch_academy(
    body: UpdateAdminAcademyRequest,
    principal: AdminPrincipal = Depends(require_admin),
    use_case: UpdateAcademyUseCase = Depends(...),  # wire via deps.py
):
    try:
        output = await use_case.execute(UpdateAcademyInput(
            academy_id=principal.academy_id, **body.model_dump(exclude_unset=True),
        ))
    except LookupError:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "academy not found")
    return AdminAcademyView(**output.__dict__)
```

Add factory functions to `deps.py` for the new use cases (`get_academy_use_case_deps`, `update_academy_use_case_deps`).

- [ ] **B1.5.4: Register the sub-router**

In `backend/v2/interfaces/admin/router.py`, add:

```python
from . import academy_routes
admin_router.include_router(academy_routes.router)
```

- [ ] **B1.5.5: Run, expect pass**

```bash
cd backend && pytest v2/tests/interface/admin/test_academy_routes.py -v
```

Expected: 3 passed.

### Task B1.6: Contract test for academy

**Files:**
- Create: `backend/v2/tests/contract/admin/test_academy_contract.py`

- [ ] **B1.6.1: Write the contract test**

```python
# backend/v2/tests/contract/admin/test_academy_contract.py
from fastapi.testclient import TestClient

REQUIRED_GET_KEYS = {"academy_id", "display_name", "timezone"}
OPTIONAL_GET_KEYS = {"contact_email", "contact_phone", "hours_text", "address"}

def test_get_academy_contract(test_client: TestClient, seeded_admin_token: str):
    res = test_client.get(
        "/api/v2/admin/academy",
        headers={"Authorization": f"Bearer {seeded_admin_token}"},
    )
    assert res.status_code == 200
    body = res.json()
    missing_required = REQUIRED_GET_KEYS - set(body.keys())
    assert not missing_required, f"missing keys: {missing_required}"
    unknown = set(body.keys()) - REQUIRED_GET_KEYS - OPTIONAL_GET_KEYS
    assert not unknown, f"unexpected keys: {unknown}"
```

- [ ] **B1.6.2: Run, expect pass**

```bash
cd backend && pytest v2/tests/contract/admin/test_academy_contract.py -v
```

### Task B1.7: Frontend client for academy

**Files:**
- Modify: `frontend/lib/api/admin.ts` (append near other admin types)

- [ ] **B1.7.1: Add types + client functions**

```typescript
// at the end of lib/api/admin.ts, before any default-export if present

export interface AdminAcademyView {
  academy_id: string;
  display_name: string;
  timezone: string;
  contact_email: string | null;
  contact_phone: string | null;
  hours_text: string | null;
  address: string | null;
}

export interface UpdateAdminAcademyRequest {
  display_name?: string;
  timezone?: string;
  contact_email?: string | null;
  contact_phone?: string | null;
  hours_text?: string | null;
  address?: string | null;
}

export function getAdminAcademy(): Promise<AdminAcademyView> {
  return apiFetch<AdminAcademyView>("/admin/academy", { method: "GET" });
}

export function updateAdminAcademy(
  payload: UpdateAdminAcademyRequest,
): Promise<AdminAcademyView> {
  return apiFetch<AdminAcademyView>("/admin/academy", {
    method: "PATCH",
    body: JSON.stringify(payload),
  });
}
```

- [ ] **B1.7.2: Add query keys**

In `frontend/lib/query/keys.ts`, add to the admin namespace:

```typescript
academy: () => ["admin", "academy"] as const,
```

- [ ] **B1.7.3: Typecheck**

```bash
cd frontend && pnpm typecheck
```

Expected: clean.

### Task B1.8: Settings page shell + tab strip

**Files:**
- Create: `frontend/components/admin/settings/settings-tabs.tsx`
- Create: `frontend/components/admin/settings/coming-next-card.tsx`
- Modify: `frontend/app/(admin)/admin/settings/page.tsx` (full rewrite)
- Create: `frontend/components/admin/settings/academy-panel.tsx`
- Create stubs (one line each, return Coming-next card): the remaining 6 panel files.

Read first: `frontend/components/ds/chip.tsx`, `card.tsx`, `typography.tsx`, `button.tsx` to confirm props.

- [ ] **B1.8.1: Write the shared Coming-next card**

```tsx
// frontend/components/admin/settings/coming-next-card.tsx
"use client";

import { Card } from "@/components/ds/card";
import { Overline } from "@/components/ds/typography";

export function ComingNextCard({
  title,
  description,
}: {
  title: string;
  description: string;
}) {
  return (
    <Card p={32}>
      <Overline>Coming next</Overline>
      <h3 className="mt-1 font-display text-lg font-semibold tracking-[-0.01em] text-rally-ink">
        {title}
      </h3>
      <p className="mt-2 text-sm text-rally-muted max-w-prose">{description}</p>
    </Card>
  );
}
```

- [ ] **B1.8.2: Write the tab strip**

```tsx
// frontend/components/admin/settings/settings-tabs.tsx
"use client";

import { useRouter, useSearchParams } from "next/navigation";

export type SettingsPanelKey =
  | "academy" | "fees" | "gateway" | "notify" | "roles" | "branding" | "data";

export const SETTINGS_PANELS: { key: SettingsPanelKey; label: string }[] = [
  { key: "academy", label: "ACADEMY" },
  { key: "fees", label: "FEES" },
  { key: "gateway", label: "GATEWAY" },
  { key: "notify", label: "NOTIFICATIONS" },
  { key: "roles", label: "ROLES" },
  { key: "branding", label: "BRANDING" },
  { key: "data", label: "DATA" },
];

export function useActivePanel(): SettingsPanelKey {
  const params = useSearchParams();
  const raw = params?.get("panel");
  if (raw && SETTINGS_PANELS.some((p) => p.key === raw)) {
    return raw as SettingsPanelKey;
  }
  return "academy";
}

export function SettingsTabs() {
  const router = useRouter();
  const active = useActivePanel();
  return (
    <div className="flex flex-wrap gap-2 border-b border-rally-line pb-3">
      {SETTINGS_PANELS.map((p) => {
        const isActive = p.key === active;
        return (
          <button
            key={p.key}
            type="button"
            onClick={() =>
              router.replace(`/admin/settings?panel=${p.key}` as never, { scroll: false })
            }
            data-testid={`settings-tab-${p.key}`}
            className="px-3 py-1.5 rounded-md font-mono text-[10px] font-bold uppercase tracking-chip transition-colors"
            style={{
              background: isActive ? "var(--rally-cobalt)" : "transparent",
              color: isActive ? "#fff" : "var(--rally-ink)",
              border: isActive ? "1px solid var(--rally-cobalt)" : "1px solid var(--rally-line)",
            }}
          >
            {p.label}
          </button>
        );
      })}
    </div>
  );
}
```

- [ ] **B1.8.3: Write the Academy panel**

```tsx
// frontend/components/admin/settings/academy-panel.tsx
"use client";

import { useEffect, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import {
  getAdminAcademy, updateAdminAcademy,
  type AdminAcademyView, type UpdateAdminAcademyRequest,
} from "@/lib/api/admin";
import { queryKeys } from "@/lib/query/keys";

import { Button } from "@/components/ds/button";
import { Card } from "@/components/ds/card";
import { LaneHeader } from "@/components/ds/lane";
import { Overline } from "@/components/ds/typography";

type FormState = Required<UpdateAdminAcademyRequest>;
const EMPTY: FormState = {
  display_name: "", timezone: "", contact_email: "", contact_phone: "",
  hours_text: "", address: "",
};

export function AcademyPanel() {
  const queryClient = useQueryClient();
  const { data, isLoading } = useQuery({
    queryKey: queryKeys.admin.academy(),
    queryFn: getAdminAcademy,
  });
  const [form, setForm] = useState<FormState>(EMPTY);
  const [original, setOriginal] = useState<FormState>(EMPTY);
  const [error, setError] = useState<string | null>(null);
  const [savedFlash, setSavedFlash] = useState(false);

  useEffect(() => {
    if (data) {
      const next: FormState = {
        display_name: data.display_name ?? "",
        timezone: data.timezone ?? "",
        contact_email: data.contact_email ?? "",
        contact_phone: data.contact_phone ?? "",
        hours_text: data.hours_text ?? "",
        address: data.address ?? "",
      };
      setForm(next);
      setOriginal(next);
    }
  }, [data]);

  const dirty = JSON.stringify(form) !== JSON.stringify(original);

  const mutation = useMutation({
    mutationFn: (patch: UpdateAdminAcademyRequest) => updateAdminAcademy(patch),
    onSuccess: (updated) => {
      queryClient.setQueryData(queryKeys.admin.academy(), updated);
      setOriginal(form);
      setSavedFlash(true);
      setError(null);
      setTimeout(() => setSavedFlash(false), 2000);
    },
    onError: (err: Error) => setError(err.message ?? "Save failed."),
  });

  const onSubmit = (e: React.FormEvent) => {
    e.preventDefault();
    if (!dirty) return;
    // Only send fields that actually changed
    const patch: UpdateAdminAcademyRequest = {};
    (Object.keys(form) as (keyof FormState)[]).forEach((k) => {
      if (form[k] !== original[k]) (patch as Record<string, unknown>)[k] = form[k];
    });
    mutation.mutate(patch);
  };

  if (isLoading) {
    return <Card p={20}><div className="h-32 animate-pulse rounded bg-rally-line/40" /></Card>;
  }

  return (
    <Card p={20} data-testid="settings-panel-academy">
      <LaneHeader index="01" title="Academy details" />
      <form onSubmit={onSubmit} className="space-y-3 max-w-xl">
        {error && <p role="alert" className="rounded-md bg-red-50 px-3 py-2 text-sm text-red-700">{error}</p>}
        {savedFlash && <p className="rounded-md bg-green-50 px-3 py-2 text-sm text-green-700">Saved.</p>}
        <Field label="Display name" required>
          <input
            type="text" required value={form.display_name}
            onChange={(e) => setForm((f) => ({ ...f, display_name: e.target.value }))}
            className={inputClass}
          />
        </Field>
        <Field label="Timezone" required>
          <input
            type="text" required value={form.timezone} placeholder="e.g. America/New_York"
            onChange={(e) => setForm((f) => ({ ...f, timezone: e.target.value }))}
            className={inputClass}
          />
        </Field>
        <Field label="Contact email">
          <input
            type="email" value={form.contact_email ?? ""}
            onChange={(e) => setForm((f) => ({ ...f, contact_email: e.target.value }))}
            className={inputClass}
          />
        </Field>
        <Field label="Contact phone">
          <input
            type="tel" value={form.contact_phone ?? ""}
            onChange={(e) => setForm((f) => ({ ...f, contact_phone: e.target.value }))}
            className={inputClass}
          />
        </Field>
        <Field label="Hours">
          <input
            type="text" value={form.hours_text ?? ""}
            onChange={(e) => setForm((f) => ({ ...f, hours_text: e.target.value }))}
            className={inputClass}
            placeholder="Mon–Fri 4–9pm, Sat 9am–5pm"
          />
        </Field>
        <Field label="Address">
          <textarea
            value={form.address ?? "" } rows={2}
            onChange={(e) => setForm((f) => ({ ...f, address: e.target.value }))}
            className={`${inputClass} resize-none`}
          />
        </Field>
        <div className="flex justify-end pt-2">
          <Button
            type="submit"
            variant={dirty ? "volt" : "secondary"}
            size="sm"
            disabled={!dirty || mutation.isPending}
          >
            {mutation.isPending ? "Saving…" : dirty ? "Save changes" : "Saved"}
          </Button>
        </div>
      </form>
    </Card>
  );
}

const inputClass =
  "w-full rounded-md border border-rally-line bg-white px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-rally-cobalt-600/30";

function Field({
  label, required, children,
}: { label: string; required?: boolean; children: React.ReactNode }) {
  return (
    <label className="block">
      <span className="mb-1 block font-mono text-[10px] font-bold uppercase tracking-overline text-rally-muted">
        {label}{required && <span aria-hidden="true" className="ml-1 text-red-500">*</span>}
      </span>
      {children}
    </label>
  );
}
```

- [ ] **B1.8.4: Stub the other 6 panels**

Each is a one-liner Coming-next card. Example for fees:

```tsx
// frontend/components/admin/settings/fees-panel.tsx
"use client";
import { ComingNextCard } from "./coming-next-card";
export function FeesPanel() {
  return (
    <ComingNextCard
      title="Fees configuration"
      description="Default monthly fee, late fee rules, and grace days will land in the B2 commit alongside the BFF endpoints."
    />
  );
}
```

Repeat for `gateway-panel.tsx`, `notify-panel.tsx`, `roles-panel.tsx`, `branding-panel.tsx`, `data-panel.tsx` with appropriate descriptions (read the spec's panel matrix for each).

- [ ] **B1.8.5: Rewrite settings/page.tsx**

```tsx
// frontend/app/(admin)/admin/settings/page.tsx
"use client";

import { Suspense } from "react";

import { SettingsTabs, useActivePanel } from "@/components/admin/settings/settings-tabs";
import { AcademyPanel } from "@/components/admin/settings/academy-panel";
import { FeesPanel } from "@/components/admin/settings/fees-panel";
import { GatewayPanel } from "@/components/admin/settings/gateway-panel";
import { NotifyPanel } from "@/components/admin/settings/notify-panel";
import { RolesPanel } from "@/components/admin/settings/roles-panel";
import { BrandingPanel } from "@/components/admin/settings/branding-panel";
import { DataPanel } from "@/components/admin/settings/data-panel";

export default function AdminSettingsPage() {
  return (
    <section data-testid="admin-settings" className="space-y-5">
      <Suspense fallback={null}>
        <SettingsTabs />
      </Suspense>
      <Suspense fallback={null}>
        <PanelBody />
      </Suspense>
    </section>
  );
}

function PanelBody() {
  const active = useActivePanel();
  switch (active) {
    case "academy":  return <AcademyPanel />;
    case "fees":     return <FeesPanel />;
    case "gateway":  return <GatewayPanel />;
    case "notify":   return <NotifyPanel />;
    case "roles":    return <RolesPanel />;
    case "branding": return <BrandingPanel />;
    case "data":     return <DataPanel />;
  }
}
```

- [ ] **B1.8.6: Typecheck + build**

```bash
cd frontend && pnpm typecheck && pnpm build
```

Expected: clean.

- [ ] **B1.8.7: Commit B1**

```bash
git add backend/v2/contexts/identity/application/get_academy_use_case.py \
        backend/v2/contexts/identity/application/update_academy_use_case.py \
        backend/v2/interfaces/admin/academy_routes.py \
        backend/v2/interfaces/admin/router.py \
        backend/v2/interfaces/admin/views.py \
        backend/v2/interfaces/admin/deps.py \
        backend/v2/contexts/identity/infrastructure/ \
        backend/v2/tests/application/identity/test_academy_use_cases.py \
        backend/v2/tests/contract/admin/test_academy_contract.py \
        backend/v2/tests/interface/admin/test_academy_routes.py \
        frontend/lib/api/admin.ts \
        frontend/lib/query/keys.ts \
        frontend/app/\(admin\)/admin/settings/page.tsx \
        frontend/components/admin/settings/

git commit -m "$(cat <<'EOF'
feat(admin/settings): Rally Settings shell + Academy panel + BFF

- 7-tab Rally Settings page with URL-driven panel selection
  (?panel=academy|fees|gateway|notify|roles|branding|data).
- AcademyPanel reads/writes the academy doc via new BFF endpoints:
    GET  /api/v2/admin/academy
    PATCH /api/v2/admin/academy
- Use cases: GetAcademyUseCase + UpdateAcademyUseCase under
  contexts/identity/application/. Per the design spec, the identity
  context owns settings configuration on the academy doc; subsequent
  panels (Fees, Notifications) follow this convention.
- Repo extended with find_by_id + update_by_id (no schema migration;
  fields are optional with safe defaults).
- Coming-next placeholder panels for Fees/Gateway/Notify/Roles/Branding/
  Data — replaced by real implementations in B2-B4.
- Frontend client: getAdminAcademy + updateAdminAcademy in
  lib/api/admin.ts; queryKeys.admin.academy() in lib/query/keys.ts.

Tests: 4 use-case tests, 3 interface tests (TestClient), 1 contract
test enforcing required/optional response keys.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

### Tasks B2.1 – B2.8: Fees panel + notifications panel

Follow the exact same pattern as B1 (DTO → use case TDD → repo helper → BFF route → contract test → frontend client → frontend panel). Two pairs of endpoints, two panels.

**Endpoints to add:**
- `GET/PATCH /api/v2/admin/academy/fees` with `default_monthly_cents`, `late_fee_cents`, `grace_days` (all optional integers, validated >= 0).
- `GET/PATCH /api/v2/admin/academy/notifications` with `dues_reminders` (bool), `attendance_alerts` (bool), `daily_digest_to_admin` (bool).

**Use cases:**
- `GetAcademyFeesUseCase`, `UpdateAcademyFeesUseCase`.
- `GetAcademyNotificationsUseCase`, `UpdateAcademyNotificationsUseCase`.

Place all four under `backend/v2/contexts/identity/application/` (per B1's locked-in context choice).

**Frontend panels:**
- `fees-panel.tsx` — number inputs for the three integer fields, "Save changes" button using the same dirty/save pattern as `academy-panel.tsx`. Validates client-side that values are >= 0.
- `notify-panel.tsx` — three toggle switches (use simple `<input type="checkbox">` styled with Tailwind; no new toggle primitive). Same dirty/save pattern.

**Per-task checklist (apply to each of Fees and Notifications):**

- [ ] Add DTO models to `views.py`.
- [ ] Write failing use-case tests (get + update).
- [ ] Implement use cases.
- [ ] Extend academy repo if needed (likely no change — fees + notify nest under existing doc).
- [ ] Add BFF routes in `academy_routes.py`.
- [ ] Wire deps in `deps.py`.
- [ ] Write interface tests + contract tests.
- [ ] Run `pytest v2/tests -k "fees or notifications or academy"`.
- [ ] Add types + client + query keys in frontend.
- [ ] Implement panel component.
- [ ] Replace the Coming-next stub in `components/admin/settings/fees-panel.tsx` / `notify-panel.tsx` with the real component.
- [ ] `pnpm typecheck && pnpm build`.

**B2 commit message:**

```
feat(admin/settings): Fees + Notifications panels + BFF

- GET/PATCH /api/v2/admin/academy/fees with default_monthly_cents,
  late_fee_cents, grace_days.
- GET/PATCH /api/v2/admin/academy/notifications with dues_reminders,
  attendance_alerts, daily_digest_to_admin toggles.
- Use cases under contexts/identity/application/ (same context as
  Academy per the B1 convention).
- FeesPanel + NotifyPanel replace their Coming-next stubs.
- Save UX: volt-yellow Save button when dirty, secondary disabled
  when clean; inline success/error toasts.
```

---

## Chunk 3: Session 3 — Settings B3 + B4 (Gateway, Roles, Data, Branding)

### Task B3.1 – B3.5: Gateway panel (read-only)

**Endpoint:** `GET /api/v2/admin/academy/gateway`.

**Response shape:**
```python
class AdminGatewayView(BaseModel):
    stripe_connected: bool
    stripe_account_id_masked: Optional[str] = None  # last 4 chars only
    manual_methods: list[str]  # ["cash", "check", "zelle", "venmo", "other"]
```

**Use case:** `GetAcademyGatewayUseCase` reads existing `stripe_account_id` from the academy doc + a `manual_methods` array (defaults to `["cash", "check"]` if absent).

**Frontend:** `gateway-panel.tsx` shows:
- "Connected to Stripe" with the masked account ID, or "Not connected — onboarding deferred" if `stripe_connected` is false.
- Manual methods list rendered as a row of `Chip variant="manual"` pills, read-only.
- Below: a Coming-next card titled "Stripe Connect onboarding" explaining that the write flow is a separate workstream.

- [ ] Tasks follow B1/B2 pattern: use case TDD → BFF route → interface test → contract test → frontend client → frontend panel → replace Coming-next stub.

### Task B3.6 – B3.10: Roles panel (real + conditional invite)

**Endpoints:**
- Reuse existing `GET /api/v2/admin/users` for the list.
- New `PATCH /api/v2/admin/users/{user_id}/role` with body `{role: "admin" | "coach" | "parent"}`.
- **Conditional new `POST /api/v2/admin/users/invite` — see decision rule below.**

**Invite decision rule (from spec, line "Roles" in panel matrix):**

- [ ] **B3.6.0: Decide invite path**

```bash
grep -rn "invite\|InviteUser\|send_invitation\|invite_user" backend/v2/contexts/identity/application/ 2>/dev/null
```

If a `send_invite` / `invite_user` / equivalent use case exists in `contexts/identity/application/`: implement the real POST endpoint + wire the invite form.

If NOT: ship the invite form section of `roles-panel.tsx` as an inline Coming-next card explaining that invite delivery infrastructure is a follow-on workstream. Drop the POST endpoint from the B3 commit. Capture the decision in the B3 commit message.

**Use case:** `ChangeUserRoleUseCase` validates target user belongs to the same academy as the requesting admin and updates the role field. Forbid changing one's own role (anti-lockout protection — capture this in a test).

**Frontend:** `roles-panel.tsx`:
- Top: search input + list of users with current role `Chip`, role-change dropdown, "Save role" inline button per row.
- Below: invite form (real or Coming-next per the decision rule).

- [ ] Standard task sequence: failing tests → impl → wire → frontend.

### Task B4.1 – B4.3: Data panel (CSV exports real + deletion Coming-next)

**No new endpoints.** Reuse existing `GET /api/v2/admin/reports/{name}.csv` endpoints.

**Frontend `data-panel.tsx`:**
- "Exports" section: list of report tiles (Students, Payments, Attendance, Audit log). Each is a `<a href="/api/v2/admin/reports/{name}.csv" download>` styled as a Rally `Card` row.
- "Deletion" section: Coming-next card explaining GDPR account-removal is a separate workstream.

### Task B4.4: Branding panel (full Coming-next)

Already stubbed in B1. Update the copy if needed; otherwise leave as-is.

- [ ] **B4 verification + commit**

```bash
cd backend && pytest v2/tests
cd frontend && pnpm typecheck && pnpm build && PLAYWRIGHT_PORT=3801 pnpm exec playwright test e2e/specs/admin-shell.spec.ts --reporter=list
```

```bash
git commit -m "feat(admin/settings): Gateway read-only + Roles + Data exports + Branding Coming-next

- GET /api/v2/admin/academy/gateway (read-only Stripe + manual methods)
- PATCH /api/v2/admin/users/{id}/role (admin-only, anti-lockout safe)
- [conditional] POST /api/v2/admin/users/invite (or Coming-next)
- DataPanel surfaces existing /admin/reports/*.csv exports
- BrandingPanel stays Coming-next (file upload infra deferred)
- Account deletion stays Coming-next on DataPanel
"
```

---

## Chunk 4: Session 4 — Restyles C1 + C2 (WORK + MONEY pages)

### Per-page restyle pattern (apply to each page below)

Files vary; the workflow is identical:

- [ ] **Step 1:** Read the existing page top-to-bottom. Identify:
  - Data hooks (`useQuery`, `useMutation`).
  - Action handlers (button onClicks, form submits).
  - UI sections (header, KPIs, table, dialogs, empty/error states).
- [ ] **Step 2:** Plan the Rally equivalent in your head, then apply edits in this order:
  1. Replace page-level `<h1>` + generic header with Rally pattern (title in topbar via SCREEN_META; page body starts with the first content section).
  2. Replace card containers with `<Card p={20}>` from `@/components/ds/card`.
  3. Replace badges with `<Chip variant=… />` from `@/components/ds/chip` (use existing `CHIP_VARIANTS`).
  4. Replace `<button class="…blue-600…">` with `<Button variant=… size="sm">` from `@/components/ds/button`.
  5. Replace metric numbers with `<BigNum size={28}>{value}</BigNum>` from `@/components/ds/typography`.
  6. Wrap section heads with `<LaneHeader index="01" title="…" />` from `@/components/ds/lane`.
  7. Avatars use `@/components/ds/avatar`.
  8. Tabular numeric cells: `font-mono tabular-nums`.
  9. Column headers: `font-mono text-[10px] font-bold uppercase tracking-overline text-rally-muted`.
  10. Empty states: `text-sm text-rally-subtle` with a friendly one-liner.
- [ ] **Step 3:** Add `data-testid` markers per the spec convention:
  - Page root: `data-testid="admin-<slug>"` (e.g. `admin-students`).
  - Table rows: `data-testid="admin-<slug>-row-<id>"`.
  - Empty state: `data-testid="admin-<slug>-empty"`.
- [ ] **Step 4:** Use `useAdminAction(<Button … />)` from `@/components/admin/admin-action-slot` for the page's primary action (if any). Do not duplicate the button in the body.
- [ ] **Step 5:** Where the Rally mockup shows a field that's not in the BFF DTO (e.g. `attendance_rate`), **omit** it. Do not fake. Queue the gap for D1 if it really matters.
- [ ] **Step 6:** `pnpm typecheck` after each page.
- [ ] **Step 7:** After all pages in a sidebar group are done: `pnpm build`, run the Playwright smoke spec, then commit the group as one commit.

### Task C1: WORK group restyles

Pages (in order):

- [ ] **C1.1: `frontend/app/(admin)/admin/students/page.tsx`**
  - Table: Avatar + name, mono parent-ID, dues `Chip` (`paid`/`overdue`/`partial`), attendance fill bar (CSS-only, `bg-rally-line` background with `bg-rally-cobalt-600` foreground at `width: ${attendance_rate*100}%`).
  - Omit `attendance_rate` row content if BFF doesn't return it; show a `—` cell instead.
- [ ] **C1.2: `frontend/app/(admin)/admin/users/page.tsx`**
  - Directory restyle. Role `Chip`: admin → `enrolled`, coach → `autopayOn`, parent → `manual`. Avatar + display name + email row + last-active date.
- [ ] **C1.3: `frontend/app/(admin)/admin/waitlist/page.tsx`**
  - List restyle. Mono position number, status `Chip` (`waitlist`/`offered`/`expired`), promote/skip/remove buttons preserved as `Button variant="primary|secondary|danger" size="sm"`.
- [ ] **C1.4: `frontend/app/(admin)/admin/pause-requests/page.tsx`**
  - Approval queue. Each row: Avatar + parent name + reason + date + status `Chip` + Approve (`Button variant="primary"`) / Decline (`Button variant="danger"`).

After all four pages restyled:

- [ ] **C1.5: Verify and commit**

```bash
cd frontend && pnpm typecheck && pnpm build && PLAYWRIGHT_PORT=3801 pnpm exec playwright test e2e/specs/admin-shell.spec.ts --reporter=list

git add frontend/app/\(admin\)/admin/students/page.tsx \
        frontend/app/\(admin\)/admin/users/page.tsx \
        frontend/app/\(admin\)/admin/waitlist/page.tsx \
        frontend/app/\(admin\)/admin/pause-requests/page.tsx

git commit -m "feat(admin/work): Rally restyle - students/users/waitlist/pause-requests

Preserves existing data wiring and actions. Replaces generic Tailwind
chrome with components/ds/* primitives (Card, Chip, Button, Avatar,
BigNum, LaneHeader, Overline). data-testid markers added per the
admin-<slug> convention. DTO gaps (e.g. attendance_rate on students)
rendered as em-dash placeholders — queued for optional D1 enrichment."
```

### Task C2: MONEY group restyles (dues + reports + coach-payslip)

- [ ] **C2.1: `frontend/app/(admin)/admin/dues/page.tsx`**
  - Outstanding-by-parent table. Mono tabular amount, `Chip` for follow-up stage (use `pending`/`overdue`/`failed`), "Send reminder" button per row wired to existing `/admin/dues-reminders` mutation.
- [ ] **C2.2: `frontend/app/(admin)/admin/reports/page.tsx`**
  - CSV export tiles for each existing `/admin/reports/*.csv` (Students, Payments, Attendance, Audit log).
  - Add `MiniBars` chart from `@/components/ds/charts` for revenue trend using `getRevenue()` data (last 6 months).
- [ ] **C2.3: `frontend/app/(admin)/admin/coach-payslip/page.tsx`**
  - Per-coach earnings cards. Each card: `Avatar` + display name + period `Chip` + `BigNum` for net earnings + breakdown rows.

After all three:

- [ ] **C2.4: Verify and commit**

```bash
cd frontend && pnpm typecheck && pnpm build && PLAYWRIGHT_PORT=3801 pnpm exec playwright test e2e/specs/admin-shell.spec.ts --reporter=list

git add frontend/app/\(admin\)/admin/dues/page.tsx \
        frontend/app/\(admin\)/admin/reports/page.tsx \
        frontend/app/\(admin\)/admin/coach-payslip/page.tsx \
        frontend/components/admin/screen-meta.ts

git commit -m "feat(admin/money): Rally restyle - dues/reports/coach-payslip"
```

---

## Chunk 5: Session 5 — C3 finance split + C4 OPS + D1 + D2 + D3

### Task C3: Finance split — expenses + payouts + finance fate

- [ ] **C3.1: Read `frontend/app/(admin)/admin/finance/page.tsx`** to identify its two real sections (expenses + payouts). Note their state, queries, mutations, dialogs.

- [ ] **C3.2: Read `frontend/app/(admin)/admin/expenses/page.tsx`** — confirm it's still the redirect alias from main (`redirect("/admin/finance")`).

- [ ] **C3.3: Write the new `expenses/page.tsx`**
  - Promote the expenses section logic from `finance/page.tsx`: table of expenses, category `Chip`, "Add expense" `Button` with create modal (Rally `RallyDialog` pattern from `messages/page.tsx`).
  - Wires to existing `listExpenses` + `createExpense` from `lib/api/admin.ts`.

- [ ] **C3.4: Write the new `payouts/page.tsx`**
  - Promote payouts section logic from `finance/page.tsx`: table of Stripe payouts, status `Chip`, arrival date.
  - Wires to existing `listPayouts`.

- [ ] **C3.5: Decide `finance/page.tsx`'s fate**

**Default per spec: delete in D2.** If the user requests a Money overview during this session, instead replace `finance/page.tsx` body with a Rally KPI card row linking to expenses/payouts/reports — but this is a separate decision branch. Do NOT prompt the user during execution if no instruction is provided; default applies.

**Capture the decision verbatim in the C3 commit message** so D2 has unambiguous instructions:

```
feat(admin/money): Rally split - expenses + payouts

Promotes the expenses + payouts sections out of /admin/finance into
their own Rally routes. Existing BFF paths (/admin/finance/expenses,
/admin/finance/payouts) unchanged.

DECISION: finance/page.tsx will be deleted in D2 cleanup. (If you
want it kept as a Money overview landing, say so before D2 runs.)
```

- [ ] **C3.6: Verify and commit C3**

```bash
cd frontend && pnpm typecheck && pnpm build
git add frontend/app/\(admin\)/admin/expenses/page.tsx \
        frontend/app/\(admin\)/admin/payouts/page.tsx
git commit -m "..."
```

### Task C4: OPS group — audit-logs

- [ ] **C4.1: `frontend/app/(admin)/admin/audit-logs/page.tsx`**
  - Table: mono timestamp, Avatar + actor name, action `Chip` (use slug-to-variant lookup; default `manual` for unknown), entity ID in mono.
  - Preserves existing `listAdminAuditLogs` wiring.

- [ ] **C4.2: Verify and commit**

```bash
cd frontend && pnpm typecheck && pnpm build && PLAYWRIGHT_PORT=3801 pnpm exec playwright test e2e/specs/admin-shell.spec.ts --reporter=list

git add frontend/app/\(admin\)/admin/audit-logs/page.tsx
git commit -m "feat(admin/ops): Rally restyle - audit-logs"
```

### Task D1: DTO enrichment (conditional)

**Run only if Phase 3/C1-C4 surfaced a real DTO gap.** Most likely candidate: `coach_name` on `AdminSessionView` (Sessions list currently shows coach as an Avatar derived from `coach_id` since the BFF doesn't return a name).

- [ ] **D1.1: Check if any restyle's commit message queued a D1 gap.**

```bash
git log --since="<session-1-start>" --grep="DTO gap" --oneline
```

If empty: skip D1.

- [ ] **D1.2: Add optional field to `AdminSessionView` in `backend/v2/interfaces/admin/views.py`**

```python
class AdminSessionView(BaseModel):
    # ... existing fields ...
    coach_name: Optional[str] = None  # batched lookup; may be absent if coach record missing
```

- [ ] **D1.3: Update `backend/v2/interfaces/admin/sessions_routes.py`**

Add a single batched lookup in the BFF use case:
```python
coach_ids = list({s["coach_id"] for s in raw_sessions})
coaches = await user_repo.find_many({"_id": {"$in": coach_ids}})
coach_name_by_id = {c["_id"]: c.get("display_name") for c in coaches}
# Attach to each view:
for view in views:
    view.coach_name = coach_name_by_id.get(view.coach_id)
```

- [ ] **D1.4: Contract test enforces field presence + no N+1**

Write a test that asserts `coach_name` appears on response and that the BFF made exactly **one** find call against the users collection (mock the repo and count calls).

- [ ] **D1.5: Update `frontend/lib/api/admin.ts`**

Add `coach_name: string | null` to `AdminSessionView`. Update `sessions/page.tsx` to render `coach_name ?? "—"` next to the Avatar.

- [ ] **D1.6: Verify and commit**

```bash
cd backend && pytest v2/tests
cd frontend && pnpm typecheck && pnpm build
git commit -m "feat(admin/sessions): optional coach_name on AdminSessionView"
```

### Task D2: Route cleanup

- [ ] **D2.1: Re-run the baseline grep**

```bash
rg "/admin/comms|/admin/billing|/admin/finance" frontend
```

Expected: only `frontend/lib/api/admin.ts` references to backend API paths `/admin/finance/*` (these stay).

If any frontend page or component still references `/admin/billing` or `/admin/comms` or `/admin/finance` as a URL, fix it before deletion.

- [ ] **D2.2: Delete superseded frontend directories**

```bash
rm -rf frontend/app/\(admin\)/admin/billing/
rm -rf frontend/app/\(admin\)/admin/finance/  # only if C3 decided delete
# admin/comms/ already git-removed in Phase 3
```

- [ ] **D2.3: Update `frontend/app/(admin)/layout.tsx` and `screen-meta.ts`**

Remove any nav match for `/admin/billing`, `/admin/comms` (already updated), `/admin/finance` (if deleted).

- [ ] **D2.4: Verify and commit**

```bash
cd frontend && pnpm typecheck && pnpm build && PLAYWRIGHT_PORT=3801 pnpm exec playwright test
git add -A
git commit -m "chore(admin): delete superseded /admin/billing and /admin/finance routes"
```

### Task D3: Playwright expansion + test_result.md handoff

- [ ] **D3.1: Expand `frontend/e2e/specs/admin-shell.spec.ts`**

Add coverage for:
- `/admin/settings` mounts + `?panel=academy` is the default.
- Each settings tab click changes the URL.
- Each restyled page mounts via its `data-testid="admin-<slug>"`.
- Mobile drawer opens and closes.

- [ ] **D3.2: Run full Playwright suite**

```bash
cd frontend && PLAYWRIGHT_PORT=3801 pnpm exec playwright test --reporter=list
```

Expected: all pass. Coach/parent specs unchanged.

- [ ] **D3.3: Run full backend pytest**

```bash
cd backend && source .venv/bin/activate && pytest v2/tests
```

Expected: all pass.

- [ ] **D3.4: Update `test_result.md`**

Append a new section dated today summarizing:
- Files changed per session (A0/A1/B1-B4/C1-C4/D1-D3).
- Routes renamed (`comms` → `messages`).
- Routes deleted (`billing/`, `finance/` if applicable, `comms/` already in Phase 3).
- New backend endpoints (7 handlers across 5 paths).
- DTO additions (`coach_name` if D1 shipped; otherwise none).
- Verifications performed: `pnpm typecheck`, `pnpm build`, full Playwright on `PLAYWRIGHT_PORT=3801`, full `pytest v2/tests`.
- Verifications **skipped**: Lighthouse perf budget run (manual check only — confirm admin landing chunk < 300 KB via build output); production deploy.
- Documented benign-warning ignore-list from Playwright (Fast Refresh, HMR, React DevTools).
- Remaining risks: dashboard attention endpoint not built; Branding storage backend deferred; Stripe Connect onboarding deferred; GDPR deletion deferred; rich Students filtering deferred.

- [ ] **D3.5: Commit D3 + final handoff**

```bash
git add frontend/e2e/specs/admin-shell.spec.ts test_result.md
git commit -m "test(admin): expand admin-shell smoke + Rally admin arc handoff in test_result.md"

git log --oneline -20  # confirm arc landed cleanly
git status --short --branch  # confirm clean working tree
```

---

## Verification matrix (end-of-arc)

| Check | Command | Expected |
|---|---|---|
| Backend tests | `cd backend && source .venv/bin/activate && pytest v2/tests` | All pass |
| Backend contract tests | `pytest v2/tests/contract` | All pass |
| Frontend typecheck | `cd frontend && pnpm typecheck` | Clean |
| Frontend build | `cd frontend && pnpm build` | Succeeds; admin landing chunk < 300 KB |
| Frontend Playwright admin smoke | `PLAYWRIGHT_PORT=3801 pnpm exec playwright test e2e/specs/admin-shell.spec.ts` | Pass |
| Frontend Playwright full | `PLAYWRIGHT_PORT=3801 pnpm exec playwright test` | Pass, no coach/parent regressions |
| Manual cross-persona smoke | Open `/admin`, `/coach/today`, `/parent/dashboard` at `localhost:3801` | All load, no app console errors |
| Git state | `git status --short --branch && git log --oneline -20` | Clean tree, expected commit chain |
| `test_result.md` | open and read | Updated with arc summary |

---

## Skills referenced

- @superpowers:test-driven-development — for every backend use case + interface test + contract test.
- @superpowers:verification-before-completion — before each commit and before claiming the arc done.
- @superpowers:executing-plans or @superpowers:subagent-driven-development — for executing this plan.
- @superpowers:requesting-code-review — before merging to main.

## Known risks (carried from spec)

- Other-worktree dev servers may collide on port 3001 → use `PLAYWRIGHT_PORT=3801`.
- LSP false-positive type errors when `node_modules` not installed in a worktree → run `pnpm install --frozen-lockfile` once per worktree.
- `git stash` of uncommitted Rally foundation already used in Phase 0; subsequent commits are clean.
- C3 finance fate default = delete. If user changes mind, capture in commit message before D2 runs.

## What this plan deliberately does NOT do

- Touch coach or parent personas (out of scope).
- Build new backend domain contexts (no `students` context, no `messages` context).
- Add a `/api/v2/admin/dashboard/attention` endpoint (deferred).
- Add Stripe Connect onboarding writes (Gateway is read-only).
- Add Branding storage backend or logo upload (Coming-next).
- Add GDPR deletion flow (Coming-next).
- Add Students filtering / pagination / search (separate follow-on phase).
- Production deploy.
